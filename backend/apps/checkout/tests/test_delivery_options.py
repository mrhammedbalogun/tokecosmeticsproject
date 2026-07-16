import pytest
from decimal import Decimal
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.carts.factories import CartFactory
from apps.carts.models import CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Currency, Region
from apps.delivery.factories import DeliveryOptionFactory
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


def test_delivery_options_for_users_address(django_user_model):
    # Fresh, unseeded country (Togo). The delivery seed (delivery 0003) gives every
    # seeded country a country-level option ("Nationwide Delivery" for NG, etc.), which
    # would leak into an exact-list assertion on NG. Togo has no seeded options, so the
    # returned list is exactly the one this test defines — preserving the original
    # intent: the endpoint returns precisely the options serving the user's address,
    # priced from the cart.
    xof = Currency.objects.create(code="XOF", symbol="CFA")
    tg = Country.objects.create(code="TG", name="Togo", currency=xof)
    lome = Region.objects.create(country_code="TG", name="Lome", level="state")
    opt = DeliveryOptionFactory(currency=xof, name="Lome Flat", price="1500.00")
    opt.regions.add(lome)

    user = django_user_model.objects.create_user(email="u@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="TG", state_region=lome)
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=xof, amount=Decimal("1000.00"))
    cart = CartFactory(user=user, country=tg, currency=xof)
    CartItem.objects.create(cart=cart, variant=variant, quantity=1, unit_price_snapshot="1000.00")

    client = APIClient()
    client.force_authenticate(user)
    r = client.get(f"/api/v1/checkout/delivery-options/?address_id={addr.id}&cart_id={cart.id}",
                   HTTP_X_COUNTRY="TG")
    assert r.status_code == 200
    assert [o["name"] for o in r.data] == ["Lome Flat"]
