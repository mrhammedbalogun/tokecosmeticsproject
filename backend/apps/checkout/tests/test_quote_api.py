"""Plan-14: read-only quote endpoint. Reuses compute_totals + validate_coupon; mutates nothing."""
import pytest
from rest_framework.test import APIClient


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

    def test_empty_or_foreign_cart_is_404(self, priced_cart):
        user, _ = priced_cart
        c = APIClient(); c.force_authenticate(user)
        res = c.post("/api/v1/checkout/quote/", {"cart_id": "00000000-0000-0000-0000-000000000000"},
                     format="json", HTTP_X_COUNTRY="NG")
        assert res.status_code == 404
