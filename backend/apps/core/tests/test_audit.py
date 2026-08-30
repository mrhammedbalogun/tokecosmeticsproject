"""The BEHAVIOURAL half of the audit guarantee, and the more important half.

`test_audit_guard.py` walks the URLconf and asserts what views DECLARE. This file
drives real HTTP requests and asserts what actually lands in the database — and it
exists in this shape because of a specific, expensive lesson from Plan-16 Task 3b.

That task's guard walker asserted that admin views declared the right authentication
class. Every assertion passed. Meanwhile a preauth token authenticated the ENTIRE
customer surface, because stock `JWTAuthentication` never read the claim those views
were declaring. **A declaration test is satisfiable by a class that ignores the thing it
declares.** From Task 4 onward, every guard walker gets a behavioural twin: not only
"does the view say it is audited", but "did one real request leave one real row".

WHAT IS DRIVEN HERE, deliberately over real HTTP with a real minted admin token rather
than `force_authenticate`:

* every write endpoint on the admin surface, once each, asserting a row appears
  (`WRITE_CASES`, with a completeness test that fails on a new endpoint);
* every read-audited endpoint, asserting a row appears with the query recorded;
* the same-transaction rule, by making the audit insert fail and asserting the mutation
  rolled back;
* the append-only fences, at the model and at the database;
* the deletion/redaction promise, end to end.

`mint_admin_token_pair` rather than `force_authenticate` is not decoration. A forced
request carries no token, so `request.auth` is None and `token_jti` would be empty — the
one field that says WHICH LOGIN acted would be untested, and the day it broke nothing
would notice.
"""
from decimal import Decimal
from urllib.parse import quote

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.authentication import mint_admin_token_pair
from apps.accounts.tests.test_admin_surface_guard import ADMIN_SURFACE
from apps.catalog.factories import ProductFactory, ProductVariantFactory
from apps.catalog.models import ProductImage
from apps.core.audit import MAX_CHANGES_BYTES, REDACTED, build_changes
from apps.core.models import AuditLog, AuditLogImmutable, Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.payments.factories import PaymentFactory

pytestmark = pytest.mark.django_db

# A recognisable, documentation-range address so a failure message says where the IP in
# the row came from. Sent as CF-Connecting-IP because that is the only header
# `throttling.client_ip` trusts — X-Forwarded-For is caller-controlled and ignored.
CLIENT_IP = "203.0.113.9"

postgres_only = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="the append-only trigger is Postgres; on the SQLite fallback save() is the only fence",
)


@pytest.fixture
def owner(django_user_model):
    """A superuser staff account, so one client can drive every scope.

    Superuser rather than four role fixtures because this file is about the AUDIT
    mechanism, not about who may reach what — `test_admin_role_matrix.py` owns that and
    would be duplicated badly by a second, weaker copy here.
    """
    return django_user_model.objects.create_user(
        email="owner@toke.test", is_staff=True, is_superuser=True
    )


@pytest.fixture
def client(owner):
    api = APIClient()
    api.credentials(
        HTTP_AUTHORIZATION=f"Bearer {mint_admin_token_pair(owner)['access']}",
        HTTP_CF_CONNECTING_IP=CLIENT_IP,
    )
    return api


def rows():
    return AuditLog.objects.order_by("pk")


def only_row() -> AuditLog:
    assert rows().count() == 1, list(rows().values("action", "model_label", "object_id"))
    return rows().first()


# ---------------------------------------------------------------------------
# 1. One exercised mutation per admin write endpoint.
# ---------------------------------------------------------------------------
#
# Each case builds the least fixture data that makes its endpoint SUCCEED, because a row
# is only written on 2xx — a case that quietly started 404ing would silently stop
# testing anything, so every case asserts its own status code first.


def _ng():
    return Country.objects.get(code="NG")


def _order(number="TC-900001", status="processing", total="1000.00"):
    ng = _ng()
    warehouse = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    warehouse.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=warehouse, quantity=8)
    order = OrderFactory(
        number=number, country=ng, currency=ng.currency, reservation_reference=number,
        grand_total=total, status=status, email="customer@example.test",
    )
    OrderItem.objects.create(
        order=order, variant=variant, product_name="X", unit_price="500.00",
        line_total=total, quantity=2, fulfillment_warehouses={"Lagos HQ": 2},
    )
    return order, variant


def _quoted_order(number):
    from apps.shipping.models import ShippingQuote

    ng = _ng()
    order = OrderFactory(
        number=number, country=ng, currency=ng.currency, status="pending_payment",
        reservation_reference=number,
    )
    ShippingQuote.objects.create(order=order, currency=order.currency)
    return order


PRODUCTS_CSV = (
    b"slug,name,brand_slug,status,short_description,category_slugs,sku,variant_name,"
    b"price_ngn,price_gbp,price_usd,price_cad\n"
    b"imported,Imported,,active,,,IMP-1,50ml,5000,,,\n"
)

STOCK_CSV_HEADER = b"sku,warehouse,quantity,reserved,available,low_stock_threshold\n"


def _case_product(client, monkeypatch):
    return client.post(
        "/api/v1/admin/products/",
        {"name": "Glow Serum", "slug": "glow-serum", "status": "active"},
        format="json",
    ), 201


def _case_category(client, monkeypatch):
    return client.post(
        "/api/v1/admin/categories/", {"name": "Skin", "slug": "skin"}, format="json"
    ), 201


def _case_brand(client, monkeypatch):
    return client.post(
        "/api/v1/admin/brands/", {"name": "Toke", "slug": "toke"}, format="json"
    ), 201


def _case_tag(client, monkeypatch):
    return client.post(
        "/api/v1/admin/tags/", {"name": "Vegan", "slug": "vegan"}, format="json"
    ), 201


def _case_collection(client, monkeypatch):
    return client.post(
        "/api/v1/admin/collections/", {"name": "New In", "slug": "new-in"}, format="json"
    ), 201


def _case_variant(client, monkeypatch):
    product = ProductFactory(slug="p-variant")
    return client.post(
        "/api/v1/admin/variants/",
        {"product": product.id, "sku": "SKU-1", "name": "50ml"},
        format="json",
    ), 201


def _case_product_image(client, monkeypatch):
    """PATCH rather than POST, because this viewset deliberately has no create route —
    uploading stays on `POST /admin/products/{slug}/images/` (see ProductImageAdminViewSet).
    So the write this endpoint must be proven to audit is an edit, not a creation.

    `image` is assigned as a bare string rather than an uploaded file: naming a FileField
    writes the name to the column and touches no storage at all, which keeps this case
    from depending on whether the environment points `STORAGES` at S3 or the filesystem.
    The PATCH only writes `alt`, so no file is ever read either.
    """
    product = ProductFactory(slug="p-image")
    image = ProductImage.objects.create(
        product=product, image="catalog/products/seed.png", alt="before", position=0
    )
    return client.patch(
        f"/api/v1/admin/images/{image.id}/", {"alt": "after"}, format="json"
    ), 200


def _case_video(client, monkeypatch):
    from apps.cms.models import MediaAsset

    product = ProductFactory(slug="p-video")
    asset = MediaAsset.objects.create(file="catalog/library/v.mp4", kind=MediaAsset.VIDEO)
    return client.post(
        "/api/v1/admin/videos/",
        {"product": product.id, "asset": asset.id},
        format="json",
    ), 201


def _case_price(client, monkeypatch):
    variant = ProductVariantFactory()
    ng = _ng()
    return client.post(
        "/api/v1/admin/prices/",
        {"variant": variant.id, "currency": ng.currency_id, "country": ng.code,
         "amount": "5000.00"},
        format="json",
    ), 201


def _case_product_csv_import(client, monkeypatch):
    upload = SimpleUploadedFile("products.csv", PRODUCTS_CSV, content_type="text/csv")
    return client.post(
        "/api/v1/admin/products/import.csv", {"file": upload}, format="multipart"
    ), 200


def _case_bank_account_create(client, monkeypatch):
    from apps.core.models import Country

    country = Country.objects.exclude(bank_account__isnull=False).first()
    return client.post(
        "/api/v1/admin/bank-accounts/",
        {"country": country.code, "currency": country.currency_id, "bank_name": "GTBank",
         "account_name": "Toke", "account_number": "0123456789"},
        format="json",
    ), 201


def _case_payment_gateway_create(client, monkeypatch):
    from apps.core.models import Country

    # A gateway name nothing seeds, so `unique_together (country, gateway)` cannot
    # collide with the migration's rows however the fixtures change.
    return client.post(
        "/api/v1/admin/payment-gateways/",
        {"country": Country.objects.first().code, "gateway": "audit-probe", "is_active": False},
        format="json",
    ), 201


def _case_coupon_create(client, monkeypatch):
    return client.post(
        "/api/v1/admin/coupons/",
        {"code": "WELCOME10", "type": "percent", "value": "10"},
        format="json",
    ), 201


def _case_region_patch(client, monkeypatch):
    from apps.core.models import Region

    region = Region.objects.first()
    if region is None:
        region = Region.objects.create(
            country_code="NG", name="Testland", level="state", is_active=True
        )
    return client.patch(
        f"/api/v1/admin/regions/{region.pk}/", {"is_active": True}, format="json"
    ), 200


def _case_delivery_option_create(client, monkeypatch):
    # Coverage is required on create (an uncovered option matches nothing), and the
    # currency must be the covered country's — so cover NG and price in NGN.
    return client.post(
        "/api/v1/admin/delivery-options/",
        {"name": "Express", "price": "2500", "currency": "NGN",
         "min_days": 1, "max_days": 2, "country_codes": ["NG"]},
        format="json",
    ), 201


def _case_sender_location_create(client, monkeypatch):
    return client.post(
        "/api/v1/admin/sender-locations/",
        {"name": "Kubwa (Abuja)", "phone": "+2347074800702",
         "address": "F01 Building Materials Market, Kubwa, FCT", "locality": "Kubwa",
         "latitude": "9.161219", "longitude": "7.355617"},
        format="json",
    ), 201


def _case_partner_patch(client, monkeypatch):
    # The seeded BrandnPack row (delivery/0017) — partners arrive by migration, never
    # POST (create is closed with 405), so the exercised write is the kill-switch PATCH.
    from apps.delivery.models import DeliveryPartner

    partner = DeliveryPartner.objects.get(code="brandnpack")
    return client.patch(
        f"/api/v1/admin/partners/{partner.pk}/", {"is_active": False}, format="json",
    ), 200


def _case_partner_zone_create(client, monkeypatch):
    from apps.core.models import Region
    from apps.delivery.models import DeliveryPartner

    partner = DeliveryPartner.objects.get(code="brandnpack")
    lagos = Region.objects.get(country_code="NG", level="state", name="Lagos", parent=None)
    ikeja = Region.objects.get(country_code="NG", level="area", parent=lagos, name="Ikeja")
    return client.post(
        "/api/v1/admin/partner-zones/",
        {"partner": partner.pk, "lga_region": ikeja.pk, "lcda_name": "Ikeja Audit",
         "areas_covered": "Allen, Opebi", "price": "3000.00"},
        format="json",
    ), 201


def _case_banner_create(client, monkeypatch):
    return client.post(
        "/api/v1/admin/banners/",
        {"title": "Summer sale", "placement": "strip"},
        format="json",
    ), 201


def _case_media_upload(client, monkeypatch):
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "salmon").save(buf, format="PNG")
    return client.post(
        "/api/v1/admin/media/",
        {"file": SimpleUploadedFile("tile.png", buf.getvalue(), "image/png")},
        format="multipart",
    ), 201


def _case_homepage_section_create(client, monkeypatch):
    return client.post(
        "/api/v1/admin/homepage-sections/",
        {"type": "editorial", "sort": 1, "config": {}},
        format="json",
    ), 201


def _case_menu_item_create(client, monkeypatch):
    return client.post(
        "/api/v1/admin/menu-items/",
        {"label": "About", "url": "/page/about", "menu": "footer"},
        format="json",
    ), 201


def _case_redirect_create(client, monkeypatch):
    return client.post(
        "/api/v1/admin/redirects/",
        {"old_path": "/old-story/", "new_path": "/page/our-story", "status_code": 301},
        format="json",
    ), 201


def _case_notification_recipient_create(client, monkeypatch):
    """Adding a recipient is the canonical "camera" case: somebody already inside,
    quietly arranging for a copy of every order to reach an address of their choosing."""
    return client.post(
        "/api/v1/admin/notification-recipients/",
        {"event": "order.paid", "email": "packing@example.com"},
        format="json",
    ), 201


def _case_training_create(client, monkeypatch):
    """Authoring a training. Owner-only (`training.manage`), and the row matters for a
    reason the other CMS writes do not share: this is the one screen whose content the
    whole team is told to trust and act on, so "who put this video in front of staff, and
    when" is the question an audit has to be able to answer."""
    return client.post(
        "/api/v1/admin/training/",
        {
            "title": "Packing a fragile order",
            "description": "How to wrap glass bottles for a Lagos rider.",
            "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "position": 1,
            "is_published": True,
        },
        format="json",
    ), 201


def _case_page_create(client, monkeypatch):
    return client.post(
        "/api/v1/admin/pages/",
        {"title": "Returns policy", "slug": "returns", "body_source": "<p>Hi</p>"},
        format="json",
    ), 201


def _case_warehouse_create(client, monkeypatch):
    return client.post(
        "/api/v1/admin/warehouses/",
        {"name": "Abuja Depot", "location_country": "NG", "priority": 2, "is_active": True},
        format="json",
    ), 201


def _case_stock_create(client, monkeypatch):
    variant = ProductVariantFactory()
    warehouse = WarehouseFactory()
    return client.post(
        "/api/v1/admin/stock/",
        {"variant": variant.id, "warehouse": warehouse.id, "low_stock_threshold": 3},
        format="json",
    ), 201


def _case_stock_adjust(client, monkeypatch):
    item = StockItemFactory(variant=ProductVariantFactory(), warehouse=WarehouseFactory(),
                            quantity=10)
    return client.post(
        f"/api/v1/admin/stock/{item.id}/adjust/",
        {"quantity": 25, "reason": "restock", "note": "delivery #4"},
        format="json",
    ), 200


def _case_stock_csv_import(client, monkeypatch):
    upload = SimpleUploadedFile("stock.csv", STOCK_CSV_HEADER, content_type="text/csv")
    return client.post(
        "/api/v1/admin/stock/import.csv", {"file": upload}, format="multipart"
    ), 200


def _case_order_transition(client, monkeypatch):
    order, _ = _order("TC-900010", status="processing")
    return client.post(
        f"/api/v1/admin/orders/{order.number}/transition/",
        {"to_status": "shipped", "message": "handed to DHL"},
        format="json",
    ), 200


def _case_order_tracking(client, monkeypatch):
    order, _ = _order("TC-900011")
    return client.patch(
        f"/api/v1/admin/orders/{order.number}/tracking/",
        {"tracking_carrier": "DHL", "tracking_number": "123"},
        format="json",
    ), 200


def _case_order_note(client, monkeypatch):
    order, _ = _order("TC-900012")
    return client.patch(
        f"/api/v1/admin/orders/{order.number}/note/",
        {"admin_note": "rang the customer"},
        format="json",
    ), 200


def _case_resolve_review(client, monkeypatch):
    order, _ = _order("TC-900013")
    order.review_reason = "short_payment"
    order.save(update_fields=["review_reason"])
    return client.post(
        f"/api/v1/admin/orders/{order.number}/resolve-review/",
        {"message": "refunded by hand"},
        format="json",
    ), 200


def _case_gateway_refund(client, monkeypatch):
    """The gateway refund path, with a fake gateway registered.

    A fake rather than bank_transfer because `BankTransferGateway` has no `refund()` —
    the live gateway's refund path IS `ManualRefundView` below. Both are exercised.
    """
    from apps.payments.gateways import registry
    from apps.payments.gateways.base import PaymentGateway, RefundResult

    class _Fake(PaymentGateway):
        code = "fakeaudit"
        supported_currencies = {"NGN"}

        def initiate(self, payment, order, return_url=""):  # pragma: no cover
            raise NotImplementedError

        def refund(self, payment, amount, reason=""):
            return RefundResult("succeeded", "rf_audit", {"ok": True})

    monkeypatch.setitem(registry._REGISTRY, "fakeaudit", _Fake())
    order, _ = _order("TC-900014")
    PaymentFactory(order=order, currency=order.currency, gateway="fakeaudit",
                   gateway_reference=order.number, amount="1000.00", status="succeeded")
    return client.post(
        f"/api/v1/admin/orders/{order.number}/refunds/",
        {"amount": "100.00", "reason": "goodwill"},
        format="json",
    ), 201


def _case_manual_refund(client, monkeypatch):
    order, _ = _order("TC-900015")
    PaymentFactory(order=order, currency=order.currency, gateway="bank_transfer",
                   gateway_reference=order.number, amount="1000.00", status="succeeded")
    return client.post(
        f"/api/v1/admin/orders/{order.number}/manual-refund/",
        {"amount": "100.00", "bank_reference": "RF-1", "note": "wired back"},
        format="json",
    ), 201


def _case_confirm_receipt(client, monkeypatch):
    order, _ = _order("TC-900016", status="pending_payment")
    PaymentFactory(order=order, currency=order.currency, gateway="bank_transfer",
                   gateway_reference=order.number, amount="1000.00", status="initiated")
    return client.post(
        f"/api/v1/admin/orders/{order.number}/confirm-payment/",
        {"amount_received": "1000.00", "bank_reference": "BT-1"},
        format="json",
    ), 200


def _case_freight_quote(client, monkeypatch):
    order = _quoted_order("TC-900020")
    return client.post(
        f"/api/v1/admin/orders/{order.number}/freight/quote/",
        {"amount": "40.00", "note": "forwarder quoted 40"},
        format="json",
    ), 200


def _case_freight_waive(client, monkeypatch):
    order = _quoted_order("TC-900021")
    client.post(f"/api/v1/admin/orders/{order.number}/freight/quote/",
                {"amount": "40.00"}, format="json")
    return client.post(
        f"/api/v1/admin/orders/{order.number}/freight/waive/",
        {"note": "goodwill"},
        format="json",
    ), 200


def _case_freight_cancel(client, monkeypatch):
    order = _quoted_order("TC-900022")
    client.post(f"/api/v1/admin/orders/{order.number}/freight/quote/",
                {"amount": "40.00"}, format="json")
    return client.post(
        f"/api/v1/admin/orders/{order.number}/freight/cancel/",
        {"note": "no answer"},
        format="json",
    ), 200


def _case_freight_receipt(client, monkeypatch):
    order = _quoted_order("TC-900023")
    client.post(f"/api/v1/admin/orders/{order.number}/freight/quote/",
                {"amount": "40.00"}, format="json")
    return client.post(
        f"/api/v1/admin/orders/{order.number}/freight/receipt/",
        {"amount_received": "40.00", "bank_reference": "FR-1"},
        format="json",
    ), 200


def _case_staff_invite(client, monkeypatch):
    return client.post(
        "/api/v1/admin/staff/invites/",
        {"email": "newhire@toke.test", "role": "Support"},
        format="json",
    ), 201


def _case_staff_remove(client, monkeypatch):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group

    member = get_user_model().objects.create_user(
        email="remove-me@toke.test", password=None, is_staff=True
    )
    member.groups.add(Group.objects.get(name="Support"))
    return client.post(f"/api/v1/admin/staff/{member.pk}/remove/", {}, format="json"), 200


def _case_staff_invite_revoke(client, monkeypatch):
    from django.contrib.auth.models import Group

    from apps.accounts.invites import issue_invite

    invite, _token = issue_invite(
        email="revoke-me@toke.test", role=Group.objects.get(name="Support"), invited_by=None
    )
    return client.post(
        f"/api/v1/admin/staff/invites/{invite.pk}/revoke/", {}, format="json"
    ), 200


# view class name -> (case, expected action). One entry per admin view that can WRITE.
# The completeness test below asserts this covers every such view, so a new write
# endpoint fails here rather than joining the surface unexercised.
def _case_gig_capture(client, monkeypatch):
    from decimal import Decimal

    from apps.delivery.models import GigShipment

    order, _ = _order("TC-900030")
    shipment = GigShipment.objects.create(order=order, status="quoted", charged=Decimal("4175.20"))

    def fake_capture(o, *, actor):
        shipment.status, shipment.waybill, shipment.cost = "created", "WB-AUDIT", Decimal("4175.20")
        shipment.save()
        return shipment

    # The service is faked: this file tests THE AUDIT WRAPPER, not GIG. The capture
    # service's own behaviour (wallet refusal, timeout limbo) is test_gig_capture.py.
    monkeypatch.setattr("apps.delivery.gig.capture.capture_shipment", fake_capture)
    return client.post(f"/api/v1/admin/orders/{order.number}/gig/capture/"), 200


def _case_gig_label(client, monkeypatch):
    from decimal import Decimal

    from apps.delivery.models import GigShipment

    order, _ = _order("TC-900031")
    GigShipment.objects.create(
        order=order, status="created", waybill="WB-AUDIT2", charged=Decimal("4175.20")
    )
    monkeypatch.setattr(
        "apps.delivery.gig.capture.fetch_label", lambda s: "https://s3.example/label.pdf"
    )
    return client.post(f"/api/v1/admin/orders/{order.number}/gig/label/"), 200


def _case_aaj_capture(client, monkeypatch):
    from decimal import Decimal

    from apps.delivery.models import AajShipment

    order, _ = _order("TC-900032")
    shipment = AajShipment.objects.create(order=order, status="quoted", charged=Decimal("2779.00"))

    def fake_capture(o, *, actor):
        shipment.status, shipment.booking_id, shipment.tracking_id = "created", "bk-audit", "AUDIT001"
        shipment.cost = Decimal("2392.00")
        shipment.save()
        return shipment

    # Faked for the same reason as the GIG case: this file tests THE AUDIT WRAPPER.
    monkeypatch.setattr("apps.delivery.aaj.capture.capture_shipment", fake_capture)
    return client.post(f"/api/v1/admin/orders/{order.number}/aaj/capture/"), 200


def _case_aaj_check(client, monkeypatch):
    from decimal import Decimal

    from apps.delivery.models import AajShipment

    order, _ = _order("TC-900033")
    AajShipment.objects.create(order=order, status="create_unconfirmed", booking_id="bk-a",
                               charged=Decimal("2779.00"))
    monkeypatch.setattr("apps.delivery.aaj.capture.check_unconfirmed", lambda o, *, actor: "created")
    return client.post(f"/api/v1/admin/orders/{order.number}/aaj/check/"), 200


def _case_aaj_void(client, monkeypatch):
    from decimal import Decimal

    from apps.delivery.models import AajShipment

    order, _ = _order("TC-900034")
    shipment = AajShipment.objects.create(order=order, status="created", booking_id="bk-v",
                                          tracking_id="AUDIT002", charged=Decimal("2779.00"))

    def fake_void(o, *, actor):
        shipment.status = "voided"
        shipment.save()
        return shipment

    monkeypatch.setattr("apps.delivery.aaj.capture.void_shipment", fake_void)
    return client.post(f"/api/v1/admin/orders/{order.number}/aaj/void/"), 200


def _case_aaj_label(client, monkeypatch):
    from decimal import Decimal

    from apps.delivery.models import AajShipment

    order, _ = _order("TC-900035")
    AajShipment.objects.create(order=order, status="created", booking_id="bk-l",
                               tracking_id="AUDIT003", charged=Decimal("2779.00"))
    monkeypatch.setattr("apps.delivery.aaj.capture.fetch_label", lambda s: "https://s3.example/aaj.pdf")
    return client.post(f"/api/v1/admin/orders/{order.number}/aaj/label/"), 200


def _case_google_review(client, monkeypatch):
    return client.post(
        "/api/v1/admin/google-reviews/",
        {"author": "Ada O.", "rating": 5, "text": "Great oil",
         "review_url": "https://g.co/kgs/abc123"},
        format="json",
    ), 201


def _case_review_hide(client, monkeypatch):
    from django.contrib.auth import get_user_model

    from apps.reviews.models import Review

    reviewer = get_user_model().objects.create_user(email="reviewer@x.com", password="pw")
    review = Review.objects.create(
        product=ProductFactory(slug="p-review-audit"), user=reviewer, rating=5, body="great"
    )
    return client.patch(
        f"/api/v1/admin/reviews/{review.pk}/", {"status": "hidden"}, format="json"
    ), 200


def _case_google_reviews_meta(client, monkeypatch):
    return client.put(
        "/api/v1/admin/google-reviews-meta/",
        {"rating": "4.8", "review_count_text": "300+",
         "profile_url": "https://g.page/toke-cosmetics"},
        format="json",
    ), 200


def _case_devices_revoke(client, monkeypatch):
    return client.post("/api/v1/auth/admin-devices/revoke/"), 200


def _payout_awaiting_review():
    """A referrer with one available commission and an open payout request.

    Built through the real services rather than by hand: a `PayoutRequest` with no
    claimed `Commission` rows behind it is a shape the production code cannot produce,
    and a case that succeeds against an impossible row proves nothing about the wrapper.
    """
    from django.contrib.auth import get_user_model

    from apps.referrals.models import Commission
    from apps.referrals.services import (
        accrue_for_order, ensure_profile, request_payout, save_payout_method,
    )
    from apps.referrals.tests.factories import make_order, ngn

    User = get_user_model()
    ref_user = User.objects.create_user(email="audit-referrer@x.com", password=None)
    profile = ensure_profile(ref_user)
    buyer = User.objects.create_user(email="audit-buyer@x.com", password=None)
    order = make_order(user=buyer, subtotal="300000.00", referral_code=profile.code)
    commission = accrue_for_order(order)
    Commission.objects.filter(pk=commission.pk).update(status="available")
    save_payout_method(
        ref_user, currency=ngn(), bank_name="GTBank", account_name="AUDIT REFERRER",
        account_number="0123456789",
    )
    return request_payout(ref_user, "NGN", accept_terms=True)


def _case_payout_approve(client, monkeypatch):
    payout = _payout_awaiting_review()
    return client.post(
        f"/api/v1/admin/referral-payouts/{payout.pk}/approve/", {}, format="json",
    ), 200


def _case_payout_reject(client, monkeypatch):
    payout = _payout_awaiting_review()
    return client.post(
        f"/api/v1/admin/referral-payouts/{payout.pk}/reject/",
        {"customer_message": "We could not match the account name."}, format="json",
    ), 200


def _case_payout_paid(client, monkeypatch):
    payout = _payout_awaiting_review()
    return client.post(
        f"/api/v1/admin/referral-payouts/{payout.pk}/mark-paid/",
        {"reference": "GTB/2026/0042"}, format="json",
    ), 200


def _referrer_for_admin_actions():
    """A referrer with a profile, for the block and adjustment cases."""
    from django.contrib.auth import get_user_model

    from apps.referrals.services import ensure_profile

    user = get_user_model().objects.create_user(email="audit-block@x.com", password=None)
    ensure_profile(user)
    return user


def _case_referrer_block(client, monkeypatch):
    user = _referrer_for_admin_actions()
    return client.post(
        f"/api/v1/admin/referrers/{user.pk}/block/",
        {"blocked": True, "reason": "Ordering through their own link."}, format="json",
    ), 200


def _case_referral_adjustment(client, monkeypatch):
    user = _referrer_for_admin_actions()
    return client.post(
        f"/api/v1/admin/referrers/{user.pk}/adjust/",
        {"currency": "NGN", "amount": "-2500.00", "kind": "clawback",
         "reason": "Refund landed after the payout went."}, format="json",
    ), 201


def _case_delivery_block_create(client, monkeypatch):
    # Plan-41: "do not offer GIG in Lagos". Country-wide granularity needs no region.
    return client.post(
        "/api/v1/admin/delivery-blocks/",
        {"service_code": "gig", "country_code": "NG"},
        format="json",
    ), 201


def _case_delivery_fee_mask_create(client, monkeypatch):
    return client.post(
        "/api/v1/admin/delivery-fee-masks/",
        {"service_code": "gig", "percent": "10.00"},
        format="json",
    ), 201


def _case_store_create(client, monkeypatch):
    from apps.core.models import Region

    lagos = Region.objects.get(country_code="NG", level="state", name="Lagos", parent=None)
    alimosho = Region.objects.get(
        country_code="NG", level="area", parent=lagos, name="Alimosho"
    )
    return client.post(
        "/api/v1/admin/stores/",
        {"name": "Beauty Hub Alimosho", "store_type": "distributor", "country": "NG",
         "state_region": lagos.pk, "area_region": alimosho.pk,
         "address": "15 Example Street, Alimosho", "phone": "+2348000000000"},
        format="json",
    ), 201


def _case_tax_settings(client, monkeypatch):
    return client.patch(
        "/api/v1/admin/tax/settings/", {"charge_tax": False}, format="json"
    ), 200


def _case_business_decisions(client, monkeypatch):
    return client.patch(
        "/api/v1/admin/business-decisions/",
        {"referrer_commission_percent": "9.00"},
        format="json",
    ), 200


def _case_tax_country(client, monkeypatch):
    return client.patch(
        "/api/v1/admin/tax/countries/GB/", {"tax_applies_to_delivery": True}, format="json"
    ), 200


def _case_marketing_settings(client, monkeypatch):
    return client.patch(
        "/api/v1/admin/marketing/settings/", {"tracking_enabled": False}, format="json"
    ), 200


def _case_marketing_channel(client, monkeypatch):
    # The list request is what seeds the five channel rows (`ensure_channel_rows`), so
    # it has to happen before the PATCH can find one — the same shape the admin screen
    # itself uses.
    client.get("/api/v1/admin/marketing/channels/")
    return client.patch(
        "/api/v1/admin/marketing/channels/meta/", {"pixel_id": "1234567890"}, format="json"
    ), 200


WRITE_CASES: dict[str, tuple] = {
    # Self-service, but still a write worth a row: it changes what a stolen laptop is
    # worth. Revoking zero devices is a success (the state the caller wanted is true).
    "AdminTrustedDeviceRevokeView": (_case_devices_revoke, "trusted_device_revoke"),
    "GoogleReviewAdminViewSet": (_case_google_review, "create"),
    "GoogleReviewsMetaAdminView": (_case_google_reviews_meta, "google_reviews_meta"),
    # Like ProductImageAdminViewSet below: the only writes are PATCH and DELETE, so
    # the action recorded is the DRF action name for the PATCH.
    "ProductReviewAdminViewSet": (_case_review_hide, "partial_update"),
    "AdminGigCaptureView": (_case_gig_capture, "gig_capture"),
    # The three money actions on the referral payout queue. `payout_paid` is the one that
    # asserts cash left the company account, which is precisely the row an auditor wants.
    "ApprovePayoutView": (_case_payout_approve, "payout_approve"),
    "RejectPayoutView": (_case_payout_reject, "payout_reject"),
    "MarkPayoutPaidView": (_case_payout_paid, "payout_paid"),
    # Blocking someone and moving their balance by hand are the two admin actions with no
    # customer-visible receipt at all, which makes the audit row the only record.
    "BlockReferrerView": (_case_referrer_block, "referrer_block"),
    "CreateAdjustmentView": (_case_referral_adjustment, "referral_adjustment"),
    "AdminGigLabelView": (_case_gig_label, "gig_label"),
    # Plan-43: the AAJ writes — capture charges, void reverses, check and label read
    # AAJ but are staff acts on an order and therefore audited like the GIG label.
    "AdminAajCaptureView": (_case_aaj_capture, "aaj_capture"),
    "AdminAajCheckView": (_case_aaj_check, "aaj_check"),
    "AdminAajVoidView": (_case_aaj_void, "aaj_void"),
    "AdminAajLabelView": (_case_aaj_label, "aaj_label"),
    "ProductAdminViewSet": (_case_product, "create"),
    "CategoryAdminViewSet": (_case_category, "create"),
    "BrandAdminViewSet": (_case_brand, "create"),
    "TagAdminViewSet": (_case_tag, "create"),
    "CollectionAdminViewSet": (_case_collection, "create"),
    "ProductVariantAdminViewSet": (_case_variant, "create"),
    # `partial_update`, not `create` and not `update`: the only writes this viewset
    # exposes are PATCH and DELETE, and the mixin prefers the DRF ACTION NAME over the
    # verb it would otherwise derive from the method — the same reason `adjust` reads as
    # `adjust` rather than as `create`.
    "ProductImageAdminViewSet": (_case_product_image, "partial_update"),
    "ProductVideoAdminViewSet": (_case_video, "create"),
    "PriceAdminViewSet": (_case_price, "create"),
    "ProductCSVImportView": (_case_product_csv_import, "import_csv"),
    # The training library's authoring half (2026-08-23). It shipped carrying
    # AdminAuditMixin and audit_serializers but with no case here, so nothing had ever
    # PROVEN a row lands — which is the exact gap this file's docstring says a
    # declaration test cannot close.
    "TrainingResourceAdminViewSet": (_case_training_create, "create"),
    "PageAdminViewSet": (_case_page_create, "create"),
    "BannerAdminViewSet": (_case_banner_create, "create"),
    "MediaAssetAdminViewSet": (_case_media_upload, "create"),
    "HomepageSectionAdminViewSet": (_case_homepage_section_create, "create"),
    "MenuItemAdminViewSet": (_case_menu_item_create, "create"),
    "RedirectAdminViewSet": (_case_redirect_create, "create"),
    "NotificationRecipientAdminViewSet": (_case_notification_recipient_create, "create"),
    "BankAccountAdminViewSet": (_case_bank_account_create, "create"),
    "CountryPaymentGatewayAdminViewSet": (_case_payment_gateway_create, "create"),
    # Tax settings (Plan-37): both change what customers pay, so both must leave rows.
    # `update` for the singleton view (RetrieveUpdateAPIView PATCH has no DRF action
    # name to prefer); `partial_update` for the viewset, same as the image editor.
    "TaxSettingsView": (_case_tax_settings, "update"),
    # Business Decisions (2026-08-27). The referral percentages are PUBLISHED TERMS, so
    # "who changed the commission rate, and when" has to leave a row — the model keeps no
    # history of its own, because every number it holds is snapshotted onto the
    # commissions and orders that used it. `update`, same as the tax singleton next door
    # and for the same reason (a RetrieveUpdateAPIView PATCH has no DRF action name).
    "BusinessDecisionsView": (_case_business_decisions, "update"),
    "TaxCountryAdminViewSet": (_case_tax_country, "partial_update"),
    # Plan-44. Both leave a row for the same reason the tax screens above do: one
    # decides whether the shop is measuring at all and whose consent is asked for first,
    # the other decides which ad account receives the shop's customer data. `update` for
    # the singleton view and `partial_update` for the viewset, same as the pair above and
    # for the same reason (a RetrieveUpdateAPIView PATCH has no DRF action name).
    "MarketingSettingsView": (_case_marketing_settings, "update"),
    "MarketingChannelAdminViewSet": (_case_marketing_channel, "partial_update"),
    "CouponAdminViewSet": (_case_coupon_create, "create"),
    "DeliveryOptionAdminViewSet": (_case_delivery_option_create, "create"),
    "RegionAdminViewSet": (_case_region_patch, "partial_update"),
    "SenderLocationAdminViewSet": (_case_sender_location_create, "create"),
    # Plan-39. The partner viewset's create is closed (partners arrive by migration),
    # so its exercised write is the kill-switch PATCH — `partial_update`, same
    # reasoning as ProductImageAdminViewSet above. The `password/` action itself is
    # driven in apps/delivery/tests/test_partner.py; its _changes override keeps the
    # secret out of the row by construction ({"password_set": True}).
    "DeliveryPartnerAdminViewSet": (_case_partner_patch, "partial_update"),
    "PartnerZoneAdminViewSet": (_case_partner_zone_create, "create"),
    # Plan-41 (declared 2026-08-21 with the store locator — these two shipped without
    # a case, so nothing was checking that a block or a mask leaves a trace).
    "DeliveryBlockAdminViewSet": (_case_delivery_block_create, "create"),
    "DeliveryFeeMaskAdminViewSet": (_case_delivery_fee_mask_create, "create"),
    # Plan-42: the store directory. Archive/restore are exercised in
    # apps/stores/tests/test_admin_api.py; this pins the create row.
    "StoreLocationAdminViewSet": (_case_store_create, "create"),
    "WarehouseAdminViewSet": (_case_warehouse_create, "create"),
    "StockItemAdminViewSet": (_case_stock_create, "create"),
    "StockCSVImportView": (_case_stock_csv_import, "import_csv"),
    "AdminOrderTransitionView": (_case_order_transition, "transition"),
    "AdminOrderTrackingView": (_case_order_tracking, "tracking"),
    "AdminOrderNoteView": (_case_order_note, "note"),
    "AdminResolveReviewView": (_case_resolve_review, "resolve_review"),
    "OrderRefundView": (_case_gateway_refund, "refund"),
    "ManualRefundView": (_case_manual_refund, "manual_refund"),
    "ConfirmManualReceiptView": (_case_confirm_receipt, "confirm_bank_transfer"),
    "QuoteFreightView": (_case_freight_quote, "freight_quote"),
    "WaiveFreightView": (_case_freight_waive, "freight_waive"),
    "CancelQuoteView": (_case_freight_cancel, "freight_cancel"),
    "FreightReceiptView": (_case_freight_receipt, "freight_receipt"),
    "StaffInviteListCreateView": (_case_staff_invite, "staff_invite"),
    "StaffInviteRevokeView": (_case_staff_invite_revoke, "staff_invite_revoke"),
    # The un-invite. The row is the only durable record of who took whose access away.
    "StaffRemoveView": (_case_staff_remove, "staff_remove"),
}

# Admin views that expose no writing method at all, so there is nothing to exercise.
# Enumerated rather than derived so that a view which LOSES its write route (or gains
# one) shows up as a change here.
READ_ONLY_VIEWS = frozenset(
    {
        # Plan-20a: both report routes are GET-only aggregate reads. The export is
        # additionally read-audited (declared in test_audit_guard.READ_AUDITED_VIEWS);
        # neither writes anything, so neither has a write case.
        "ReportView",
        "ReportExportView",
        # Plan-18b: the customer list and detail are GET-only by design (the viewset
        # docstring argues why editing a customer does not belong here), so there is no
        # write case. Read-audited — declared in test_audit_guard.READ_AUDITED_VIEWS.
        "CustomerAdminViewSet",
        # Plan-43: the AAJ panel and table are GET-only, read-audited like GIG's.
        "AdminAajShipmentView",
        "AdminAajShipmentListView",
        # Plan-32a: the fulfilment panel is GET-only; its writes are the two views
        # above. Read-audited — declared in test_audit_guard.READ_AUDITED_VIEWS.
        "AdminGigShipmentView",
        # The referral payout queue: GET-only by design — its writes are the three views
        # above, each with its own scope and its own audit case. Read-audited, because it
        # is the one endpoint that unmasks a bank account number (declared in
        # test_audit_guard.READ_AUDITED_VIEWS).
        "PayoutQueueViewSet",
        # The referrer list and one referrer's adjustment history: GET-only: their writes
        # are BlockReferrerView and CreateAdjustmentView above. Both read-audited
        # (declared in test_audit_guard.READ_AUDITED_VIEWS).
        "ReferrerListView",
        "ReferrerAdjustmentsView",
        # Plan-35: the deliveries table — GET-only by design (the table reads, the
        # order page acts). Read-audited — declared in READ_AUDITED_VIEWS.
        "AdminGigShipmentListView",
        "AdminOrderListView",
        "AdminOrderDetailView",
        "AdminRefundsOwedView",
        "StockMovementListView",
        "ProductCSVExportView",
        # Both GET-only. Their read rows are driven in
        # apps/orders/tests/test_admin_order_export_and_invoice.py.
        "AdminOrderCSVExportView",
        "AdminOrderInvoiceView",
        "StockCSVExportView",
        "AuditLogListView",
        "AdminMeView",
        # GET-only, and its read row is driven end to end in
        # `apps/core/tests/test_admin_search.py` — which owns the raw-term/per-type-count
        # shape, the 90-day tombstone and the deleted-account tombstone, none of which any
        # other endpoint has.
        "AdminSearchView",
        # The staff roster. GET-only and deliberately NOT read-audited: the scope is held
        # by one person, who already knows who their colleagues are, and the acts that
        # CHANGE the roster (invite, revoke) are audited at their own endpoints. Auditing
        # the read would bury those events in rows generated by looking at them.
        "StaffListView",
        # Plan-41: the service picker behind the block/mask forms — a GET-only list of
        # service codes, no PII, so no write case and no read audit. It carries the
        # mixin so that "not audited" is a recorded decision (see the view).
        "DeliveryServiceListView",
        # The partner deliveries table: GET-only, the GIG table's sibling. Read-audited
        # — declared in test_audit_guard.READ_AUDITED_VIEWS.
        "AdminPartnerShipmentListView",
        # What staff open from the Training menu (2026-08-23): GET-only, and deliberately
        # NOT read-audited — the titles of internal how-to videos are not PII, and a row
        # every time somebody opens the list would bury the reads this table exists for.
        # Authoring is the audited half, at TrainingResourceAdminViewSet above.
        "TrainingLibraryView",
        # Plan-44's conversion outbox: GET-only, and READ-audited rather than
        # write-audited (test_audit_guard.py declares it). It stores the body actually
        # sent to each ad platform — hashed customer identifiers, plus a raw IP and user
        # agent for Meta — so opening it is a PII read, and there is no write to record.
        "ConversionEventAdminViewSet",
    }
)


def test_the_write_cases_cover_every_admin_write_endpoint():
    """Completeness, so this file is a guarantee rather than a snapshot.

    Without it, a twenty-eighth admin endpoint is simply absent from `WRITE_CASES`, every
    parametrised case still passes, and the suite reports green while one staff action
    leaves no row. That is exactly the failure mode `test_admin_surface_guard.py` was
    rewritten to remove, and the same argument applies here.
    """
    covered = set(WRITE_CASES) | READ_ONLY_VIEWS
    assert covered == set(ADMIN_SURFACE), (
        f"admin views with no audit case and no read-only declaration: "
        f"{sorted(set(ADMIN_SURFACE) - covered)}; "
        f"cases for views that no longer exist: {sorted(covered - set(ADMIN_SURFACE))}"
    )


@pytest.mark.parametrize("view_name", sorted(WRITE_CASES))
def test_every_admin_write_endpoint_writes_a_row(client, owner, monkeypatch, view_name):
    """**The behavioural twin.** One real request per write endpoint, one real row.

    Asserted per case: the request SUCCEEDED (a case that started 404ing would otherwise
    test nothing), exactly one row exists, and it carries the actor, the actor's email
    snapshot, the jti of the token that made the request, and the client IP.

    The jti assertion is the reason this file mints a real token instead of using
    `force_authenticate`. It is the field that distinguishes "the owner did this" from
    "somebody holding the owner's Tuesday session did this", and it is only populated
    when a real credential is presented.
    """
    case, expected_action = WRITE_CASES[view_name]
    AuditLog.objects.all().delete()  # ignore rows a case's own setup made through HTTP

    response, expected_status = case(client, monkeypatch)
    assert response.status_code == expected_status, (
        f"{view_name}: the case must SUCCEED or it proves nothing — "
        f"{response.status_code} {getattr(response, 'data', b'')}"
    )

    row = rows().last()
    assert row is not None, f"{view_name} wrote no audit row"
    assert row.action == expected_action, f"{view_name} recorded action={row.action!r}"
    assert row.actor_id == owner.pk
    assert row.actor_email == owner.email
    assert row.client_ip == CLIENT_IP
    assert row.token_jti, (
        f"{view_name} recorded no token jti — the row says WHO but not WHICH SESSION, "
        f"which is the field that matters on the day a staff token is stolen"
    )


def test_a_stock_adjustment_is_not_recorded_as_an_ordinary_create(client, monkeypatch):
    """A router maps `POST /stock/` and `POST /stock/1/adjust/` onto the same class and
    the same HTTP method. Recording both as "create" would make the single most
    consequential inventory operation — the one that sets the number deciding whether an
    order can be placed at all — indistinguishable from adding a row, which is why the
    mixin prefers the DRF action name over the verb."""
    AuditLog.objects.all().delete()
    response, expected = _case_stock_adjust(client, monkeypatch)

    assert response.status_code == expected, response.data
    row = only_row()
    assert row.action == "adjust"
    assert row.model_label == "inventory.stockitem"
    assert row.changes == {"quantity": 25, "reason": "restock", "note": "delivery #4"}


# ---------------------------------------------------------------------------
# 2. Reads. The revision to design ruling 4, driven.
# ---------------------------------------------------------------------------


def test_listing_orders_records_the_search_term_and_the_result_count(client):
    """The canonical insider event: somebody searched the customer base and got rows.

    A log of writes only cannot see this at all — nothing changed. What makes the row
    useful is the QUERY: "listed every order matching @example.test, 1 result" is the
    sentence, and the count is the scale of what left the building. The rows themselves
    are never stored; a second copy of the customer list inside the audit table would be
    an exfiltration aid rather than a control.
    """
    _order("TC-900030")
    response = client.get("/api/v1/admin/orders/?search=example.test&status=processing")

    assert response.status_code == 200
    row = only_row()
    assert row.action == "list"
    assert row.model_label == "orders.order"
    assert row.changes["query"] == {"search": "example.test", "status": "processing"}
    assert row.changes["result_count"] == 1
    assert "customer@example.test" not in str(row.changes), (
        "the response payload must never be stored — only the query and the count"
    )


def test_opening_one_order_records_which_one(client):
    order, _ = _order("TC-900031")
    assert client.get(f"/api/v1/admin/orders/{order.number}/").status_code == 200

    row = only_row()
    assert (row.action, row.model_label, row.object_id) == ("read", "orders.order", order.number)


def test_exporting_the_catalogue_is_recorded(client):
    """A bulk egress with no personal data in it, audited anyway — the judgement call is
    argued at `ProductCSVExportView`. Whoever can round-trip the whole price list is
    doing something worth one row a month."""
    assert client.get("/api/v1/admin/products/export.csv").status_code == 200
    assert only_row().action == "export_csv"


def test_reading_the_audit_log_is_itself_audited(client):
    """The one place in the codebase where reading a table writes to it.

    Deliberate: `changes` holds other people's data, so by the PII-read rule it qualifies
    on its own merits — and "who has been reading the audit log, and what were they
    filtering for" is the behaviour that precedes somebody deciding which rows to try to
    remove. It does not recurse: one read makes one row.
    """
    _order("TC-900032")
    client.patch("/api/v1/admin/orders/TC-900032/note/", {"admin_note": "x"}, format="json")
    before = rows().count()

    response = client.get("/api/v1/admin/audit/?action=note")

    assert response.status_code == 200
    assert rows().count() == before + 1
    assert rows().last().changes["query"] == {"action": "note"}


def test_a_catalogue_list_is_not_audited(client):
    """The other side of the ruling, asserted so "audit everything" cannot creep in.

    Routine catalogue reads carry no personal data and happen on every admin page load.
    Auditing them would bury the rows that matter under navigation noise, which is the
    failure mode that makes people stop reading a log.
    """
    assert client.get("/api/v1/admin/products/").status_code == 200
    assert rows().count() == 0


# ---------------------------------------------------------------------------
# 3. Same transaction: both or neither.
# ---------------------------------------------------------------------------


def test_a_failing_audit_insert_rolls_the_mutation_back(client, monkeypatch):
    """**The rule that makes this table worth trusting, driven rather than asserted.**

    An admin surface where "the refund went through and nothing recorded it" is possible
    has an audit log that answers a question it cannot be relied on for. So the write is
    inside the mutation's own transaction, and an audit failure takes the mutation with
    it. Fail-closed is the right direction here specifically: this is a staff endpoint,
    used a handful of times a day, where an unrecordable action should simply not happen.

    Simulated by breaking the INSERT itself, which is the failure mode that would really
    occur (a full disk, a broken column, a constraint) — not by patching the mixin, which
    would only prove that the mixin calls what it calls.
    """
    from apps.catalog.models import Category
    from apps.core.models import AuditLog as AuditLogModel

    def boom(self, *args, **kwargs):
        raise DatabaseError("no room at the inn")

    monkeypatch.setattr(AuditLogModel, "save", boom)

    with pytest.raises(DatabaseError):
        client.post("/api/v1/admin/categories/", {"name": "Ghost", "slug": "ghost"},
                    format="json")

    assert not Category.objects.filter(slug="ghost").exists(), (
        "the category was created even though its audit row could not be written — "
        "the mutation and the audit insert are not in the same transaction"
    )


# ---------------------------------------------------------------------------
# 4. `changes`: the allowlist and its two size caps.
# ---------------------------------------------------------------------------


def test_only_allowlisted_keys_reach_the_row(client):
    """The whole answer to "what stops a secret-named field being stored".

    Nothing stops the key ARRIVING — the body is whatever the caller sent, and here it
    carries a plausible-looking `api_secret`. What the allowlist guarantees is that an
    unlisted key is never written, whatever it is called. A scrub-by-name denylist was
    refused for exactly the reason this test is written with an invented field name:
    a denylist only knows the names somebody thought of.
    """
    response = client.post(
        "/api/v1/admin/brands/",
        {"name": "Toke", "slug": "toke", "api_secret": "sk_live_deadbeef",
         "description": "ignored"},
        format="json",
    )

    assert response.status_code == 201
    changes = only_row().changes
    assert changes == {"name": "Toke", "slug": "toke"}
    assert "sk_live_deadbeef" not in str(changes)


def test_an_oversized_body_becomes_a_marker_that_keeps_the_keys():
    """An unbounded JSONField fed from request bodies is a disk-DoS lever: a hostile
    staff session can PATCH a 50MB field as fast as the network allows and every attempt
    is stored forever.

    Truncation keeps the KEYS and marks itself. A silently truncated row reads as a
    complete one, and somebody would later conclude the staff member edited two fields.

    NOTE the input has to be a COLLECTION to reach this path at all. A single huge
    string is absorbed by the per-VALUE cap (see the next test) and never reaches the
    per-row budget — which is the whole point of having both. A list survives per-value
    capping 50 times over, so 50 x ~512 chars clears 8KB and the row-level marker is
    what remains. Getting this wrong once already produced two tests asserting
    contradictory things about the same function.
    """
    changes = build_changes({"name": ["x" * 1_000] * 50, "slug": "y"}, ("name", "slug"))

    assert changes["__truncated__"] is True
    assert changes["__keys__"] == ["name", "slug"]
    assert len(str(changes).encode()) < MAX_CHANGES_BYTES


def test_one_huge_value_does_not_truncate_the_whole_row():
    """The per-value cap, which is why the per-row cap is rarely reached.

    Without it a single 8KB-minus-one value fills the row's entire budget and takes every
    other key down with it into a marker — so the interesting fields (which one was
    touched) lose to the boring one.
    """
    changes = build_changes({"name": "x" * 5_000, "slug": "keep-me"}, ("name", "slug"))

    assert changes["slug"] == "keep-me"
    assert changes["name"].endswith("[truncated]")


def test_a_file_upload_is_recorded_as_text_not_as_bytes(client):
    """Multipart bodies put `UploadedFile` objects in `request.data`, which `JSONField`
    cannot store. Coerced to `str()` — for a file that is its name. Recorded here so the
    CSV import endpoints cannot start 500ing on a JSON-serialisation error inside a
    transaction that would then roll the import back."""
    upload = SimpleUploadedFile("products.csv", PRODUCTS_CSV, content_type="text/csv")
    response = client.post("/api/v1/admin/products/import.csv", {"file": upload},
                           format="multipart")

    assert response.status_code == 200
    assert only_row().action == "import_csv"


# ---------------------------------------------------------------------------
# 5. Append-only: the model fence, the database fence, and the FK.
# ---------------------------------------------------------------------------


def test_an_existing_row_cannot_be_re_saved(client):
    """The application-level fence. Weakest of the three and the one that catches the
    accidental case: a future view that loads a row and calls `.save()`."""
    client.post("/api/v1/admin/tags/", {"name": "T", "slug": "t"}, format="json")
    row = only_row()
    row.action = "something-else"

    with pytest.raises(AuditLogImmutable):
        row.save()


@postgres_only
def test_the_database_refuses_to_rewrite_an_audit_row(client):
    """The fence that actually holds: `QuerySet.update()` never calls `save()`, so
    without the trigger "the model is immutable" would be a claim about one method."""
    client.post("/api/v1/admin/tags/", {"name": "T", "slug": "t"}, format="json")
    pk = only_row().pk

    with pytest.raises(DatabaseError), transaction.atomic():
        AuditLog.objects.filter(pk=pk).update(action="tampered")


@postgres_only
def test_the_database_refuses_to_delete_an_audit_row(client):
    """Deleting the row is the cleanest way to erase an action; it is refused outright.

    HONEST SCOPE, and it is written on the migration too: a database superuser can
    disable the trigger and root has the data directory. This stops the attacker the log
    is actually pointed at — one operating through the application.
    """
    client.post("/api/v1/admin/tags/", {"name": "T", "slug": "t"}, format="json")

    with pytest.raises(DatabaseError), transaction.atomic():
        AuditLog.objects.all().delete()


@postgres_only
def test_the_database_permits_exactly_the_redaction_update(client):
    """`changes` is the one column that may be rewritten, and only because a deleted
    customer's values have to be removable. Everything else — including the timestamp —
    is refused, so the property is "the contents of one column can be blanked", not "rows
    can be edited".

    THE FORBIDDEN TIMESTAMP IS A DAY AWAY, NOT `now()`, AND THAT MATTERS. The trigger
    compares `to_jsonb(NEW)` against `to_jsonb(OLD)`, and a `created_at` rewritten to
    `timezone.now()` lands microseconds from the value `auto_now_add` wrote moments
    earlier — close enough to render identically and compare equal, so the trigger
    correctly sees no change and the test flakily "failed" by not raising. It was
    order-dependent only because timing was. Backdating an audit row is the realistic
    attack anyway: making an action look like it happened at a different time is the
    point, and nobody rewrites a timestamp to the value it already has.
    """
    client.post("/api/v1/admin/tags/", {"name": "T", "slug": "t"}, format="json")
    pk = only_row().pk

    AuditLog.objects.filter(pk=pk).update(changes={"name": REDACTED})
    assert AuditLog.objects.get(pk=pk).changes == {"name": REDACTED}

    with pytest.raises(DatabaseError), transaction.atomic():
        AuditLog.objects.filter(pk=pk).update(
            created_at=timezone.now() - timezone.timedelta(days=1)
        )


def test_deleting_the_actor_keeps_the_row_and_its_email_snapshot(client, owner):
    """SET_NULL plus an immutable snapshot, together.

    CASCADE would make deleting your own staff account the cleanest way to delete
    everything you ever did. PROTECT would make offboarding a support ticket. SET_NULL
    keeps the row, and `actor_email` is why that is not a row saying nobody did it.
    """
    client.post("/api/v1/admin/tags/", {"name": "T", "slug": "t"}, format="json")
    owner.delete()

    row = only_row()
    assert row.actor_id is None
    assert row.actor_email == "owner@toke.test"


# ---------------------------------------------------------------------------
# 6. The mirror line: the database is not the only copy.
# ---------------------------------------------------------------------------


def test_the_security_log_mirrors_the_row_with_keys_but_never_values(client, caplog):
    """Keys and ids only, and that one rule buys three things at once.

    The database stops being the sole copy, so somebody who can blank `changes` (the one
    column the trigger permits) has not erased that the action happened. Customer PII
    stays out of the log stream and therefore out of Sentry breadcrumbs. And because no
    caller-supplied VALUE is ever interpolated, the log-injection lesson from
    `apps/core/log_safety.py` cannot bite here.
    """
    with caplog.at_level("INFO", logger="apps.security"):
        client.post(
            "/api/v1/admin/brands/",
            {"name": "Secretive Brand", "slug": "secretive"},
            format="json",
        )

    mirrored = [r.getMessage() for r in caplog.records if r.getMessage().startswith("audit ")]
    assert len(mirrored) == 1, mirrored
    line = mirrored[0]
    assert "keys=name,slug" in line
    assert "Secretive Brand" not in line, "the mirror must carry keys and ids, never values"
    assert "owner@toke.test" in line  # the actor IS an id, and is the point of the line


# ---------------------------------------------------------------------------
# 7. Retention: the row survives, the values do not.
# ---------------------------------------------------------------------------


def test_deleting_a_customer_hollows_out_their_audit_rows_but_keeps_them(
    client, django_user_model
):
    """**Both promises, held at once.** Create, mutate, delete-and-anonymise, then look.

    Deletion means "your data is gone" and it has to be true of the audit table too, or
    the table is a quiet second copy of everything a customer ever gave us. Audit
    integrity means "staff member X edited customer 123's order at 14:02" stays provable.
    The two are only compatible if the row survives and the VALUES do not — which is
    exactly what is asserted below, in both directions.

    The search row is the interesting one: it has no object id, because a list has no
    object, so it is found by matching the customer's address inside `changes`. Without
    that second pass, deleting a customer would leave their email sitting in the audit
    table as somebody's search term.
    """
    from apps.accounts.tasks import anonymize_deleted_accounts

    customer = django_user_model.objects.create_user(
        email="doomed@example.test", password="Str0ng!pass9"
    )
    order, _ = _order("TC-900040")
    order.user = customer
    order.email = customer.email
    order.save(update_fields=["user", "email"])

    client.get(f"/api/v1/admin/orders/?search={customer.email}")
    client.patch(f"/api/v1/admin/orders/{order.number}/note/",
                 {"admin_note": "spoke to doomed@example.test about delivery"}, format="json")
    assert rows().count() == 2

    customer.is_active = False
    customer.deletion_requested_at = timezone.now() - timezone.timedelta(days=31)
    customer.save(update_fields=["is_active", "deletion_requested_at"])
    assert anonymize_deleted_accounts() == 1

    surviving = list(rows())
    assert len(surviving) == 2, "the rows must survive — deletion is not amnesia"
    assert [r.action for r in surviving] == ["list", "note"]
    assert all(r.actor_email == "owner@toke.test" for r in surviving)
    assert all(r.client_ip == CLIENT_IP for r in surviving)

    # The keys stay: WHICH field was touched is still on the record.
    assert set(surviving[0].changes) == {"query", "result_count"}
    assert set(surviving[1].changes) == {"admin_note"}
    # The values do not.
    for row in surviving:
        assert "doomed@example.test" not in str(row.changes)
        assert all(value == REDACTED for value in row.changes.values())


def test_redaction_is_idempotent(client, django_user_model):
    """The sweep re-runs, and a poison row must not stop it. Re-redacting an already
    hollowed row is a no-op rather than a second UPDATE, which also keeps it from
    tripping the append-only trigger with a pointless write."""
    from apps.core.audit import redact_audit_values

    order, _ = _order("TC-900041")
    client.patch(f"/api/v1/admin/orders/{order.number}/note/",
                 {"admin_note": "hello"}, format="json")

    assert redact_audit_values(model_labels_and_ids=[("orders.order", [order.number])]) == 1
    assert redact_audit_values(model_labels_and_ids=[("orders.order", [order.number])]) == 0
    assert only_row().changes == {"admin_note": REDACTED}


# ---------------------------------------------------------------------------
# 8. The endpoint the mixin cannot cover.
# ---------------------------------------------------------------------------


def test_accepting_a_staff_invite_writes_a_row_even_though_nobody_is_logged_in(settings):
    """**The one action on this surface that had to be audited by hand.**

    `AdminAuditMixin` attributes a row to `request.user`, and this endpoint has none: the
    caller proves an invite token, not a session. Left to the mixin it would write
    nothing — which would make CREATING AN ADMINISTRATOR the single staff action with no
    row, and that is the exact hole the table exists to close.

    The actor recorded is the new staff member. `invited_by` on the invite, plus the
    `staff_invite` row from when it was sent, is what ties it back to the Owner.
    """
    from django.contrib.auth.models import Group

    from apps.accounts.invites import issue_invite

    invite, raw_token = issue_invite(
        email="newhire@toke.test", role=Group.objects.get(name="Support"), invited_by=None
    )

    response = APIClient().post(
        "/api/v1/admin/staff/invites/accept/",
        {"token": raw_token, "password": "Str0ng!pass9"},
        format="json",
    )

    assert response.status_code == 200, response.data
    row = only_row()
    assert row.action == "staff_invite_accept"
    assert row.actor_email == "newhire@toke.test"
    assert row.object_id == str(invite.pk)
    assert row.changes == {"role": "Support", "new_account": True}
    assert "Str0ng!pass9" not in str(row.changes), (
        "the request body carries a password; `changes` here is built from server-side "
        "facts and must never be built from request.data"
    )


def test_the_audit_list_endpoint_filters_by_actor_model_and_date(client, owner):
    """The read side, briefly. `actor` matches the SNAPSHOT column rather than the FK,
    which is the only way to find the rows of a staff member whose account has since been
    deleted — precisely when somebody goes looking."""
    order, _ = _order("TC-900050")
    client.patch(f"/api/v1/admin/orders/{order.number}/note/", {"admin_note": "n"},
                 format="json")
    client.post("/api/v1/admin/tags/", {"name": "T", "slug": "t"}, format="json")

    by_model = client.get("/api/v1/admin/audit/?model=orders.order")
    assert [r["action"] for r in by_model.data["results"]] == ["note"]

    by_actor = client.get("/api/v1/admin/audit/?actor=owner@")
    assert by_actor.data["count"] >= 2

    # quote() the timestamp: `+` is a SPACE in a query string, so an un-encoded
    # `+00:00` offset arrives as `2026-07-30T06:33:52 00:00` and parses as nothing.
    future = quote((timezone.now() + timezone.timedelta(days=1)).isoformat())
    assert client.get(f"/api/v1/admin/audit/?after={future}").data["count"] == 0


def test_an_unparseable_date_filter_is_a_400_not_a_500(client, owner):
    """Found while fixing the test above, and worth its own pin.

    Passing the raw string to `created_at__gte=` lets Django's field validation raise
    from inside the queryset, which DRF does not catch — so a mistyped filter was a 500,
    and now that Sentry is live, an error event. Filter values are user input; a bad one
    is a 400. The un-encoded `+` is the realistic way to send one by accident, so it is
    the case pinned here.
    """
    naive = (timezone.now() + timezone.timedelta(days=1)).isoformat()  # `+` left raw

    response = client.get(f"/api/v1/admin/audit/?after={naive}")

    assert response.status_code == 400
    assert "after" in response.data
    assert client.get("/api/v1/admin/audit/?before=not-a-date").status_code == 400


def test_the_amount_and_the_two_overrides_are_on_the_record_for_a_bank_transfer(client):
    """The single most consequential row this table will hold at launch.

    Bank transfer is the only live gateway, so this endpoint is where goods are released
    against money nobody has verified but the person clicking — and
    `accept_discrepancy` / `allow_duplicate_reference` are the two switches that turn OFF
    the guards against shipping twice against one transfer. If any keys belong in the
    audit table, it is these.
    """
    order, _ = _order("TC-900060", status="pending_payment")
    PaymentFactory(order=order, currency=order.currency, gateway="bank_transfer",
                   gateway_reference=order.number, amount="1000.00", status="initiated")

    response = client.post(
        f"/api/v1/admin/orders/{order.number}/confirm-payment/",
        # `note` is REQUIRED by confirm_manual_receipt whenever accept_discrepancy
        # switches the guard off (services.py: "accepting an amount discrepancy requires
        # a reason"). That makes it the most audit-worthy key on the endpoint: the
        # override says the guard was bypassed, and the note says why.
        {
            "amount_received": "900.00",
            "bank_reference": "BT-9",
            "accept_discrepancy": True,
            "note": "customer underpaid by 100, agreed to write off",
        },
        format="json",
    )

    assert response.status_code == 200, response.data
    row = only_row()
    assert row.action == "confirm_bank_transfer"
    assert row.object_id == order.number
    assert row.changes == {
        "amount_received": "900.00",
        "bank_reference": "BT-9",
        "accept_discrepancy": True,
        "note": "customer underpaid by 100, agreed to write off",
    }
    assert Decimal(row.changes["amount_received"]) == Decimal("900.00")
