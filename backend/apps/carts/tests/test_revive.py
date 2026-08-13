"""Abandoned carts come back. The abandon task (idle >3h) is a marketing marker,
not a deletion — a shopper returning days later must find their items intact."""
import pytest
from types import SimpleNamespace

from apps.carts.factories import CartFactory
from apps.carts.models import Cart, CartItem
from apps.carts.services import get_or_create_cart, merge_guest_cart
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country

pytestmark = pytest.mark.django_db


def _ng():
    return Country.objects.get(code="NG")


def _request(user=None, cart_id=None):
    headers = {"X-Cart-Id": str(cart_id)} if cart_id else {}
    return SimpleNamespace(country=_ng(), user=user, headers=headers)


def test_authed_user_gets_abandoned_cart_revived(django_user_model):
    ng = _ng()
    user = django_user_model.objects.create_user(email="r@x.com", password="pw")
    cart = CartFactory(user=user, country=ng, currency=ng.currency, status="abandoned")

    got = get_or_create_cart(_request(user=user))

    assert got.id == cart.id
    assert got.status == "active"


def test_authed_user_active_cart_wins_over_abandoned(django_user_model):
    ng = _ng()
    user = django_user_model.objects.create_user(email="r2@x.com", password="pw")
    CartFactory(user=user, country=ng, currency=ng.currency, status="abandoned")
    active = CartFactory(user=user, country=ng, currency=ng.currency, status="active")

    assert get_or_create_cart(_request(user=user)).id == active.id


def test_guest_abandoned_cart_revived_by_header():
    ng = _ng()
    cart = CartFactory(user=None, country=ng, currency=ng.currency, status="abandoned")

    got = get_or_create_cart(_request(cart_id=cart.id))

    assert got.id == cart.id
    assert got.status == "active"


def test_guest_converted_cart_is_not_revived():
    ng = _ng()
    cart = CartFactory(user=None, country=ng, currency=ng.currency, status="converted")

    got = get_or_create_cart(_request(cart_id=cart.id))

    assert got.id != cart.id
    assert Cart.objects.get(id=cart.id).status == "converted"


def test_merge_folds_abandoned_guest_cart(django_user_model):
    ng = _ng()
    user = django_user_model.objects.create_user(email="r3@x.com", password="pw")
    variant = ProductVariantFactory()
    # No stock rows: set_quantity caps at 0, so use a variant-free assertion via status.
    guest = CartFactory(user=None, country=ng, currency=ng.currency, status="abandoned")
    CartItem.objects.create(cart=guest, variant=variant, quantity=2, unit_price_snapshot="100.00")

    merged = merge_guest_cart(user, guest.id, ng)

    assert merged.user_id == user.id
    assert Cart.objects.get(id=guest.id).status == "converted"


def test_merge_revives_users_own_abandoned_cart(django_user_model):
    ng = _ng()
    user = django_user_model.objects.create_user(email="r4@x.com", password="pw")
    mine = CartFactory(user=user, country=ng, currency=ng.currency, status="abandoned")

    merged = merge_guest_cart(user, None, ng)

    assert merged.id == mine.id
    assert merged.status == "active"
