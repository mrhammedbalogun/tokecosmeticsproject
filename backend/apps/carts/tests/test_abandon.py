import pytest
from datetime import timedelta
from django.utils import timezone

from apps.carts.factories import CartFactory
from apps.carts.models import Cart
from apps.carts.tasks import abandon_stale_carts
from apps.core.models import Country

pytestmark = pytest.mark.django_db


def _ng():
    return Country.objects.get(code="NG")


def test_carts_idle_over_3h_are_abandoned():
    ng = _ng()
    fresh = CartFactory(country=ng, currency=ng.currency)
    stale = CartFactory(country=ng, currency=ng.currency)
    # Push stale cart's updated_at back 4 hours (bypass auto_now with a queryset update).
    Cart.objects.filter(id=stale.id).update(updated_at=timezone.now() - timedelta(hours=4))

    n = abandon_stale_carts()

    assert n == 1
    assert Cart.objects.get(id=stale.id).status == "abandoned"
    assert Cart.objects.get(id=fresh.id).status == "active"
