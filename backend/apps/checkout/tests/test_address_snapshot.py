"""The placement snapshot carries the pin (Plan-32b ruling 2): capture reads
door coordinates from the order forever, even after the address row changes."""
from decimal import Decimal

import pytest

from apps.accounts.models import Address
from apps.checkout.services.checkout import _address_snapshot
from apps.core.models import Region

pytestmark = pytest.mark.django_db


def _address(django_user_model, **extra):
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    ikeja = Region.objects.create(country_code="NG", name="Ikeja", level="area", parent=lagos)
    user = django_user_model.objects.create_user(email="snap@x.com", password="pw")
    return Address.objects.create(
        user=user, first_name="Ada", phone="08012345678", line1="1 Allen Ave",
        country_code="NG", state_region=lagos, area_region=ikeja, **extra,
    )


def test_snapshot_carries_the_pin_as_floats(django_user_model):
    addr = _address(django_user_model,
                    latitude=Decimal("6.618570"), longitude=Decimal("3.342590"))
    snap = _address_snapshot(addr)
    assert snap["latitude"] == 6.618570
    assert snap["longitude"] == 3.342590


def test_snapshot_without_a_pin_says_none_not_zero(django_user_model):
    snap = _address_snapshot(_address(django_user_model))
    assert snap["latitude"] is None
    assert snap["longitude"] is None
