import pytest
from rest_framework.test import APIClient

from apps.accounts.claims import claim_legacy_orders
from apps.accounts.verification import make_verify_token
from apps.core.models import Country
from apps.orders.factories import OrderFactory

PW = "Str0ng!pass9"


def _guest_order(number, email):
    ng = Country.objects.get(code="NG")
    return OrderFactory(number=number, country=ng, currency=ng.currency,
                        user=None, email=email, source="legacy_ng")


@pytest.mark.django_db
def test_claim_attaches_userless_orders_matching_email(django_user_model):
    user = django_user_model.objects.create_user(email="ada@b.com", password=PW)
    o1 = _guest_order("NG-1001", "ada@b.com")
    o2 = _guest_order("NG-1002", "ADA@b.com")           # case-insensitive match
    other = _guest_order("NG-1003", "someone@else.com")  # must NOT be claimed

    n = claim_legacy_orders(user)

    assert n == 2
    o1.refresh_from_db()
    o2.refresh_from_db()
    other.refresh_from_db()
    assert o1.user_id == user.id
    assert o2.user_id == user.id
    assert other.user_id is None


@pytest.mark.django_db
def test_claim_ignores_orders_that_already_have_a_user(django_user_model):
    """The user__isnull guard: an order already attached to an account is never
    re-pointed. Re-running claim for the owner returns 0 — the owned order is not
    matched, so nothing is silently re-written."""
    owner = django_user_model.objects.create_user(email="ada@b.com", password=PW)
    ng = Country.objects.get(code="NG")
    order = OrderFactory(number="NG-2001", country=ng, currency=ng.currency,
                         user=owner, email="ada@b.com")

    assert claim_legacy_orders(owner) == 0     # already owned → not re-claimed
    order.refresh_from_db()
    assert order.user_id == owner.id


@pytest.mark.django_db
def test_verify_email_endpoint_marks_verified_and_claims(django_user_model):
    user = django_user_model.objects.create_user(email="ada@b.com", password=PW)
    _guest_order("NG-3001", "ada@b.com")
    token = make_verify_token(user.email)

    r = APIClient().post("/api/v1/auth/verify-email/", {"token": token}, format="json")

    assert r.status_code == 200
    user.refresh_from_db()
    assert user.email_verified_at is not None
    from apps.orders.models import Order
    assert Order.objects.get(number="NG-3001").user_id == user.id


@pytest.mark.django_db
def test_verify_email_rejects_a_bad_token():
    r = APIClient().post("/api/v1/auth/verify-email/", {"token": "garbage"}, format="json")
    assert r.status_code == 400
