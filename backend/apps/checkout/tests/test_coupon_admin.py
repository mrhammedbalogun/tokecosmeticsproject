"""Plan-19b: the coupon admin.

The model and its redemption ledger have existed since Plan-08c and production holds zero
of both — because nothing could create one without a database client. This is the launch
marketing lever finally becoming reachable.
"""
import pytest
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.checkout.models import Coupon, CouponRedemption

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def test_requires_staff():
    assert APIClient().get("/api/v1/admin/coupons/").status_code in (401, 403)


def test_creates_a_percentage_coupon(client):
    response = client.post(
        "/api/v1/admin/coupons/",
        {"code": "welcome10", "type": "percent", "value": "10", "usage_limit": 100},
        format="json",
    )

    assert response.status_code == 201, response.data
    # Stored upper-case: uniqueness is case-insensitive at the database, so normalising
    # here stops two people creating SUMMER and summer and meeting at checkout.
    assert Coupon.objects.get(pk=response.data["id"]).code == "WELCOME10"


def test_A_FIXED_COUPON_WITHOUT_A_CURRENCY_IS_REFUSED(client):
    """It would be a coupon that silently never applies: `resolve` cannot compare an
    amount with no currency to a cart total, and nobody would know why."""
    response = client.post(
        "/api/v1/admin/coupons/",
        {"code": "FLAT500", "type": "fixed", "value": "500"},
        format="json",
    )

    assert response.status_code == 400
    assert "currency" in response.data


def test_usage_is_reported_from_the_ledger(client):
    coupon = Coupon.objects.create(code="USED", type="percent", value=5)
    CouponRedemption.objects.create(coupon=coupon, order_number="TC-1")
    CouponRedemption.objects.create(coupon=coupon, order_number="TC-2")

    row = next(r for r in client.get("/api/v1/admin/coupons/").data["results"] if r["code"] == "USED")

    # From the rows that actually record a redemption, not a counter that can drift.
    assert row["redemption_count"] == 2


def test_A_COUPON_CANNOT_BE_DELETED(client):
    """`CouponRedemption` points at it, so deleting a used code detaches the ledger rows
    that say what discount an order got."""
    coupon = Coupon.objects.create(code="KEEP", type="percent", value=5)

    response = client.delete(f"/api/v1/admin/coupons/{coupon.pk}/")

    assert response.status_code == 405
    assert Coupon.objects.filter(pk=coupon.pk).exists()
