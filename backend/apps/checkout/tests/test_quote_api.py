"""Plan-14: read-only quote endpoint. Reuses compute_totals + validate_coupon; mutates nothing."""
import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.carts.factories import CartFactory
from apps.core.models import Country, Region
from apps.delivery.factories import DeliveryOptionFactory


@pytest.mark.django_db
class TestQuoteApi:
    def test_requires_auth(self, priced_cart):  # fixture: (user, cart) with >=1 priced line, NG
        res = APIClient().post("/api/v1/checkout/quote/", {"cart_id": str(priced_cart[1].id)}, format="json")
        assert res.status_code in (401, 403)

    def test_returns_totals_for_a_cart(self, priced_cart):
        user, cart = priced_cart
        c = APIClient(); c.force_authenticate(user)
        res = c.post("/api/v1/checkout/quote/", {"cart_id": str(cart.id)}, format="json", HTTP_X_COUNTRY="NG")
        assert res.status_code == 200
        t = res.data["totals"]
        assert set(t) == {"subtotal", "discount", "delivery", "tax", "grand_total", "currency"}
        assert t["discount"] == "0.00" and t["delivery"] == "0.00"
        assert res.data["coupon"] == {"ok": True}   # no code supplied → trivially ok

    def test_invalid_coupon_reports_error_code_without_failing(self, priced_cart):
        user, cart = priced_cart
        c = APIClient(); c.force_authenticate(user)
        res = c.post("/api/v1/checkout/quote/",
                     {"cart_id": str(cart.id), "coupon_code": "NOPE"}, format="json", HTTP_X_COUNTRY="NG")
        assert res.status_code == 200
        assert res.data["coupon"]["ok"] is False and res.data["coupon"]["error_code"] == "not_found"
        assert res.data["totals"]["discount"] == "0.00"   # invalid coupon discounts nothing

    def test_unknown_cart_is_404(self, priced_cart):
        user, _ = priced_cart
        c = APIClient(); c.force_authenticate(user)
        res = c.post("/api/v1/checkout/quote/", {"cart_id": "00000000-0000-0000-0000-000000000000"},
                     format="json", HTTP_X_COUNTRY="NG")
        assert res.status_code == 404

    def test_malformed_cart_id_is_400(self, priced_cart):
        user, _ = priced_cart
        c = APIClient(); c.force_authenticate(user)
        res = c.post("/api/v1/checkout/quote/", {"cart_id": "not-a-uuid"}, format="json", HTTP_X_COUNTRY="NG")
        assert res.status_code == 400

    def test_empty_cart_returns_zero_totals(self, priced_cart):
        # Deliberately a real, existing, owned cart with zero items (not a fake id) —
        # pins the intentional absence of an empty-cart guard here (unlike
        # DeliveryOptionsView): a preview of an empty cart is a legitimate 200 with
        # all-zero totals, not an error.
        user, _ = priced_cart
        ng = Country.objects.get(code="NG")
        empty_cart = CartFactory(user=user, country=ng, currency=ng.currency, kind="express")
        c = APIClient(); c.force_authenticate(user)
        res = c.post("/api/v1/checkout/quote/", {"cart_id": str(empty_cart.id)},
                     format="json", HTTP_X_COUNTRY="NG")
        assert res.status_code == 200
        t = res.data["totals"]
        assert t["subtotal"] == "0.00" and t["grand_total"] == "0.00"

    def test_delivery_amount_applies_for_valid_address_and_option(self, priced_cart):
        user, cart = priced_cart
        lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
        opt = DeliveryOptionFactory(currency=cart.currency, name="Lagos Flat", price="1500.00")
        opt.regions.add(lagos)
        addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)

        c = APIClient(); c.force_authenticate(user)
        res = c.post("/api/v1/checkout/quote/",
                     {"cart_id": str(cart.id), "address_id": addr.id, "delivery_option_id": opt.id},
                     format="json", HTTP_X_COUNTRY="NG")
        assert res.status_code == 200
        t = res.data["totals"]
        assert t["delivery"] == "1500.00"
        # priced_cart: qty 2 @ 1000.00 = 2000.00 subtotal (NG prices_include_tax=True) +
        # 1500.00 delivery = 3500.00 grand_total (delivery isn't itself taxed further) —
        # matches the same math test_checkout_flow.py asserts for the real checkout.
        assert t["subtotal"] == "2000.00"
        assert t["grand_total"] == "3500.00"

    def test_delivery_option_not_matching_address_falls_back_to_zero(self, priced_cart):
        user, cart = priced_cart
        addr = Address.objects.create(user=user, line1="1 St", country_code="NG")
        c = APIClient(); c.force_authenticate(user)
        res = c.post("/api/v1/checkout/quote/",
                     {"cart_id": str(cart.id), "address_id": addr.id, "delivery_option_id": 999999999},
                     format="json", HTTP_X_COUNTRY="NG")
        assert res.status_code == 200
        assert res.data["totals"]["delivery"] == "0.00"
