import pytest
from decimal import Decimal

from rest_framework.test import APIClient

from apps.carts.factories import CartFactory
from apps.carts.models import CartItem
from apps.carts.services import add_item, set_quantity
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


def _ng_with_stock(variant, qty):
    # NG + NGN are seeded (core migration 0003); fetch rather than create.
    ng = Country.objects.get(code="NG")
    ngn = ng.currency
    wh = WarehouseFactory(location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    StockItemFactory(variant=variant, warehouse=wh, quantity=qty)
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    return ng


def test_add_item_snapshots_price_and_creates_line():
    variant = ProductVariantFactory()
    ng = _ng_with_stock(variant, qty=10)
    cart = CartFactory(country=ng, currency=ng.currency)

    add_item(cart, variant, 2, ng)

    line = CartItem.objects.get(cart=cart, variant=variant)
    assert line.quantity == 2
    assert line.unit_price_snapshot == Decimal("1000.00")


def test_add_item_merges_into_existing_line():
    variant = ProductVariantFactory()
    ng = _ng_with_stock(variant, qty=10)
    cart = CartFactory(country=ng, currency=ng.currency)
    add_item(cart, variant, 2, ng)
    add_item(cart, variant, 3, ng)
    assert CartItem.objects.get(cart=cart, variant=variant).quantity == 5


def test_add_item_capped_at_available_stock():
    variant = ProductVariantFactory()
    ng = _ng_with_stock(variant, qty=3)
    cart = CartFactory(country=ng, currency=ng.currency)
    add_item(cart, variant, 10, ng)  # only 3 exist
    assert CartItem.objects.get(cart=cart, variant=variant).quantity == 3


def test_set_quantity_zero_removes_line():
    variant = ProductVariantFactory()
    ng = _ng_with_stock(variant, qty=10)
    cart = CartFactory(country=ng, currency=ng.currency)
    add_item(cart, variant, 2, ng)
    set_quantity(cart, variant, 0, ng)
    assert not CartItem.objects.filter(cart=cart, variant=variant).exists()


def test_guest_cart_roundtrip_via_header():
    variant = ProductVariantFactory()
    _ng_with_stock(variant, qty=10)  # seeds stock + NGN price for NG
    client = APIClient()

    # First GET with no header creates a cart and returns its id.
    r = client.get("/api/v1/cart/", HTTP_X_COUNTRY="NG")
    assert r.status_code == 200
    cart_id = r.data["id"]

    # Add an item using that cart id.
    r = client.post(
        "/api/v1/cart/items/", {"variant_id": variant.id, "quantity": 2},
        format="json", HTTP_X_COUNTRY="NG", HTTP_X_CART_ID=cart_id,
    )
    assert r.status_code == 200
    assert r.data["items"][0]["quantity"] == 2
    assert r.data["subtotal"] == "2000.00"


def test_malformed_cart_id_header_does_not_500():
    """A corrupted X-Cart-Id cookie/header must not crash: treat it as no cart
    and hand back a fresh guest cart, not an ORM ValidationError (HTTP 500)."""
    _ng_with_stock(ProductVariantFactory(), qty=5)
    client = APIClient()

    r = client.get("/api/v1/cart/", HTTP_X_COUNTRY="NG", HTTP_X_CART_ID="not-a-uuid")

    assert r.status_code == 200
    assert r.data["id"]  # a brand-new guest cart id, not a crash


def test_patch_and_delete_line(django_user_model):
    variant = ProductVariantFactory()
    _ng_with_stock(variant, qty=10)  # seeds stock + NGN price for NG
    user = django_user_model.objects.create_user(email="c@x.com", password="pw")
    client = APIClient()
    client.force_authenticate(user)

    client.post("/api/v1/cart/items/", {"variant_id": variant.id, "quantity": 4},
                format="json", HTTP_X_COUNTRY="NG")
    r = client.patch(f"/api/v1/cart/items/{variant.id}/", {"quantity": 1},
                     format="json", HTTP_X_COUNTRY="NG")
    assert r.data["items"][0]["quantity"] == 1
    r = client.delete(f"/api/v1/cart/items/{variant.id}/", HTTP_X_COUNTRY="NG")
    assert r.data["items"] == []


def test_add_capped_to_zero_returns_409_out_of_stock():
    """A stock cap that eats the whole add is an explicit 409, not a silent 200 —
    the storefront shows "just sold out" instead of opening an empty drawer."""
    variant = ProductVariantFactory()
    _ng_with_stock(variant, qty=0)
    client = APIClient()

    r = client.post("/api/v1/cart/items/", {"variant_id": variant.id, "quantity": 1},
                    format="json", HTTP_X_COUNTRY="NG")

    assert r.status_code == 409
    assert r.data["code"] == "out_of_stock"


def test_add_beyond_existing_line_cap_returns_409():
    variant = ProductVariantFactory()
    _ng_with_stock(variant, qty=3)
    client = APIClient()
    r = client.post("/api/v1/cart/items/", {"variant_id": variant.id, "quantity": 3},
                    format="json", HTTP_X_COUNTRY="NG")
    assert r.status_code == 200
    cart_id = r.data["id"]

    # Line is already at the cap — another add can't grow it.
    r = client.post("/api/v1/cart/items/", {"variant_id": variant.id, "quantity": 1},
                    format="json", HTTP_X_COUNTRY="NG", HTTP_X_CART_ID=cart_id)
    assert r.status_code == 409
    assert r.data["code"] == "out_of_stock"


def test_add_partially_capped_is_still_200():
    """Requested 5, only 2 in stock: the line grows to 2 — that's a success, not
    a sold-out; the server-clamped cart is the response."""
    variant = ProductVariantFactory()
    _ng_with_stock(variant, qty=2)
    client = APIClient()
    r = client.post("/api/v1/cart/items/", {"variant_id": variant.id, "quantity": 5},
                    format="json", HTTP_X_COUNTRY="NG")
    assert r.status_code == 200
    assert r.data["items"][0]["quantity"] == 2


def test_cart_line_carries_the_product_picture_and_slug():
    """The cart drawer shows a thumbnail per line; without these fields it could only
    show text. Same picture the confirmation email uses — one answer, from
    apps.catalog.images — so the cart and the email cannot disagree."""
    from io import BytesIO

    from django.core.files.base import ContentFile
    from PIL import Image as PILImage

    from apps.carts.serializers import serialize_cart
    from apps.catalog.models import ProductImage

    variant = ProductVariantFactory()
    ng = _ng_with_stock(variant, qty=5)
    buffer = BytesIO()
    PILImage.new("RGB", (900, 900), (200, 180, 150)).save(buffer, format="JPEG")
    picture = ProductImage(product=variant.product, alt="A jar of shea butter")
    picture.image.save("jar.jpg", ContentFile(buffer.getvalue()), save=False)
    picture.save()

    cart = CartFactory(country=ng, currency=ng.currency)
    add_item(cart, variant, 1, ng)

    line = serialize_cart(cart, ng)["items"][0]
    assert picture.thumbnail.name in line["image"]  # thumbnail preferred over the original
    assert line["image"].startswith("http")  # absolute — next/image cannot use a bare key
    assert line["product_slug"] == variant.product.slug


def test_cart_line_without_a_picture_serializes_null_not_an_error():
    from apps.carts.serializers import serialize_cart

    variant = ProductVariantFactory()
    ng = _ng_with_stock(variant, qty=5)
    cart = CartFactory(country=ng, currency=ng.currency)
    add_item(cart, variant, 1, ng)

    line = serialize_cart(cart, ng)["items"][0]
    assert line["image"] is None
