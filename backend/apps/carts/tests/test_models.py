import pytest
from django.db import IntegrityError

from apps.carts.models import Cart
from apps.core.models import Country

pytestmark = pytest.mark.django_db


def _ng():
    # NG + NGN are guaranteed by the core seed migration (0003) in every test DB;
    # fetch rather than create (creating would violate the PK uniqueness).
    return Country.objects.get(code="NG")


def test_one_active_standard_cart_per_user(django_user_model):
    ng = _ng()
    user = django_user_model.objects.create_user(email="a@x.com", password="pw")
    Cart.objects.create(user=user, kind="standard", country=ng, currency=ng.currency)
    with pytest.raises(IntegrityError):
        Cart.objects.create(user=user, kind="standard", country=ng, currency=ng.currency)


def test_guest_may_hold_many_carts():
    ng = _ng()
    Cart.objects.create(user=None, country=ng, currency=ng.currency)
    Cart.objects.create(user=None, country=ng, currency=ng.currency)  # no constraint violation


from apps.carts.services import get_or_create_cart


class _Req:
    """Minimal stand-in for a DRF request (user + country + headers)."""

    def __init__(self, user, country, cart_id=None):
        self.user = user
        self.country = country
        self.headers = {"X-Cart-Id": str(cart_id)} if cart_id else {}


def test_authed_get_or_create_returns_single_standard_cart(django_user_model):
    ng = _ng()
    user = django_user_model.objects.create_user(email="b@x.com", password="pw")
    c1 = get_or_create_cart(_Req(user, ng))
    c2 = get_or_create_cart(_Req(user, ng))
    assert c1.id == c2.id  # same active cart reused


def test_guest_get_or_create_makes_new_when_no_header():
    ng = _ng()

    class Anon:
        is_authenticated = False

    cart = get_or_create_cart(_Req(Anon(), ng))
    assert cart.user_id is None and cart.status == "active"
