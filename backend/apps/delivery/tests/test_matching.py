import pytest
from decimal import Decimal

from apps.core.models import Country, Currency, Region
from apps.delivery.factories import DeliveryOptionFactory
from apps.delivery.services import options_for_address

pytestmark = pytest.mark.django_db


class FakeAddress:
    """Duck-typed address: only the fields the matcher reads."""

    def __init__(self, country_code, state_region=None, area_region=None):
        self.country_code = country_code
        self.state_region = state_region
        self.area_region = area_region


def _ng():
    # NGN + NG are seeded by core migration 0003; get_or_create avoids IntegrityError.
    ngn, _ = Currency.objects.get_or_create(code="NGN", defaults={"symbol": "₦"})
    ng, _ = Country.objects.get_or_create(
        code="NG", defaults={"name": "Nigeria", "currency": ngn, "is_default": True}
    )
    return ng


def _lagos_tree():
    # Lagos + Ikeja are seeded by delivery migration 0002; get_or_create reuses them.
    lagos, _ = Region.objects.get_or_create(
        country_code="NG", name="Lagos", parent=None, defaults={"level": "state"}
    )
    ikeja, _ = Region.objects.get_or_create(
        country_code="NG", name="Ikeja", parent=lagos, defaults={"level": "area"}
    )
    eti_osa, _ = Region.objects.get_or_create(
        country_code="NG", name="Eti-Osa", parent=lagos, defaults={"level": "area"}
    )
    return lagos, ikeja, eti_osa


def test_country_level_option_matches_any_address_in_country():
    ng = _ng()
    opt = DeliveryOptionFactory(currency=ng.currency, name="GIG Nationwide")
    opt.countries.add(ng)
    addr = FakeAddress("NG")
    matched = options_for_address(addr, lines=[], subtotal=Decimal("0"))
    assert [o["name"] for o in matched] == ["GIG Nationwide"]


def test_state_coverage_matches_every_lga_in_that_state():
    ng = _ng()
    lagos, ikeja, _ = _lagos_tree()
    opt = DeliveryOptionFactory(currency=ng.currency, name="Lagos State Flat")
    opt.regions.add(lagos)  # covers the whole state
    addr = FakeAddress("NG", state_region=lagos, area_region=ikeja)
    matched = options_for_address(addr, lines=[], subtotal=Decimal("0"))
    assert any(o["name"] == "Lagos State Flat" for o in matched)


def test_specific_lga_coverage_matches_only_that_lga():
    ng = _ng()
    lagos, ikeja, eti_osa = _lagos_tree()
    opt = DeliveryOptionFactory(currency=ng.currency, name="Ikeja Same-Day")
    opt.regions.add(ikeja)
    in_ikeja = FakeAddress("NG", state_region=lagos, area_region=ikeja)
    in_eti = FakeAddress("NG", state_region=lagos, area_region=eti_osa)
    assert any(o["name"] == "Ikeja Same-Day" for o in options_for_address(in_ikeja, [], Decimal("0")))
    assert not any(o["name"] == "Ikeja Same-Day" for o in options_for_address(in_eti, [], Decimal("0")))


def test_inactive_options_excluded_and_sorted_by_sort():
    ng = _ng()
    DeliveryOptionFactory(currency=ng.currency, name="Off", is_active=False).countries.add(ng)
    a = DeliveryOptionFactory(currency=ng.currency, name="A", sort=2)
    b = DeliveryOptionFactory(currency=ng.currency, name="B", sort=1)
    a.countries.add(ng); b.countries.add(ng)
    names = [o["name"] for o in options_for_address(FakeAddress("NG"), [], Decimal("0"))]
    assert names == ["B", "A"]  # sorted by sort; inactive excluded
