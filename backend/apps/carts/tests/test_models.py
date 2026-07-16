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
