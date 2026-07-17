import pytest
from decimal import Decimal

from apps.core.models import Country, Currency, Region
from apps.delivery.factories import DeliveryOptionFactory
from apps.delivery.models import DeliveryOption
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


def _isolated_country():
    """A country with no seeded delivery options (Task-6's 0003 seeds NG/GB/US/CA/ZZ),
    so the exact-list assertions below compare only options this test creates."""
    cur, _ = Currency.objects.get_or_create(code="XCU", defaults={"symbol": "X"})
    country, _ = Country.objects.get_or_create(
        code="XL", defaults={"name": "Testland", "currency": cur}
    )
    return country


def _clear_seeded_options():
    """Drop the options seeded by delivery migration 0003 (NG/GB/US/CA/ZZ) so the
    exact-list assertions below see only what the test creates. Needed because that
    migration names ZZ's option "International Standard" (f"{country.name} Standard",
    and ZZ is named "International") and gives GB one too — both collide with the
    RoW tests. The other tests here dodge this via _isolated_country()."""
    DeliveryOption.objects.all().delete()


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
    country = _isolated_country()
    opt = DeliveryOptionFactory(currency=country.currency, name="GIG Nationwide")
    opt.countries.add(country)
    addr = FakeAddress(country.code)
    matched = options_for_address(addr, lines=[], subtotal=Decimal("0"), country=country)
    assert [o["name"] for o in matched] == ["GIG Nationwide"]


def test_state_coverage_matches_every_lga_in_that_state():
    ng = _ng()
    lagos, ikeja, _ = _lagos_tree()
    opt = DeliveryOptionFactory(currency=ng.currency, name="Lagos State Flat")
    opt.regions.add(lagos)  # covers the whole state
    addr = FakeAddress("NG", state_region=lagos, area_region=ikeja)
    matched = options_for_address(addr, lines=[], subtotal=Decimal("0"), country=ng)
    assert any(o["name"] == "Lagos State Flat" for o in matched)


def test_specific_lga_coverage_matches_only_that_lga():
    ng = _ng()
    lagos, ikeja, eti_osa = _lagos_tree()
    opt = DeliveryOptionFactory(currency=ng.currency, name="Ikeja Same-Day")
    opt.regions.add(ikeja)
    in_ikeja = FakeAddress("NG", state_region=lagos, area_region=ikeja)
    in_eti = FakeAddress("NG", state_region=lagos, area_region=eti_osa)
    assert any(o["name"] == "Ikeja Same-Day" for o in options_for_address(in_ikeja, [], Decimal("0"), country=ng))
    assert not any(o["name"] == "Ikeja Same-Day" for o in options_for_address(in_eti, [], Decimal("0"), country=ng))


def test_inactive_options_excluded_and_sorted_by_sort():
    country = _isolated_country()
    DeliveryOptionFactory(currency=country.currency, name="Off", is_active=False).countries.add(country)
    a = DeliveryOptionFactory(currency=country.currency, name="A", sort=2)
    b = DeliveryOptionFactory(currency=country.currency, name="B", sort=1)
    a.countries.add(country)
    b.countries.add(country)
    names = [o["name"] for o in options_for_address(FakeAddress(country.code), [], Decimal("0"), country=country)]
    assert names == ["B", "A"]  # sorted by sort; inactive excluded


@pytest.mark.django_db
def test_unknown_iso_code_falls_back_to_rest_of_world():
    """A German address must reach the ZZ option. This is the bug: DE matches no
    Country row and no Region, so the customer got zero options and could not check out."""
    _clear_seeded_options()
    zz = Country.objects.get(code="ZZ")
    opt = DeliveryOption.objects.create(
        name="International Standard", kind="manual", price=Decimal("25.00"),
        currency=zz.currency, min_days=3, max_days=10,
    )
    opt.countries.add(zz)

    matched = options_for_address(FakeAddress("DE"), lines=[], subtotal=Decimal("0"), country=zz)

    assert [o["name"] for o in matched] == ["International Standard"]


@pytest.mark.django_db
def test_known_country_with_no_options_does_not_fall_back_to_rest_of_world():
    """The fallback trigger is UNKNOWN COUNTRY CODE, never ZERO OPTIONS FOUND.
    If deactivating every GB option silently served GB customers the ZZ option,
    Britons would be charged international rates instead of checkout stopping."""
    _clear_seeded_options()  # incl. the seeded "United Kingdom Standard" — GB must have zero
    zz = Country.objects.get(code="ZZ")
    gb = Country.objects.get(code="GB")
    opt = DeliveryOption.objects.create(
        name="International Standard", kind="manual", price=Decimal("25.00"),
        currency=zz.currency, min_days=3, max_days=10,
    )
    opt.countries.add(zz)

    matched = options_for_address(FakeAddress("GB"), lines=[], subtotal=Decimal("0"), country=gb)

    assert matched == []


@pytest.mark.django_db
def test_rest_of_world_address_never_matches_a_nigerian_region_option():
    """Region matching is ORed with country matching. A DE address must not pick up
    'Isolo area N1000' through the region leg."""
    _clear_seeded_options()  # incl. the seeded ZZ option, which a DE address legitimately matches
    zz = Country.objects.get(code="ZZ")
    lagos, _ikeja, _eti = _lagos_tree()
    ng_opt = DeliveryOption.objects.create(
        name="Isolo area delivery", kind="manual", price=Decimal("1000.00"),
        currency=Currency.objects.get(code="NGN"), min_days=1, max_days=2,
    )
    ng_opt.regions.add(lagos)

    matched = options_for_address(FakeAddress("DE"), lines=[], subtotal=Decimal("0"), country=zz)

    assert matched == []


@pytest.mark.django_db
def test_region_option_is_not_reached_by_an_address_in_another_country():
    """The test above cannot see the region guard: FakeAddress("DE") has no regions, so
    the region leg never runs and the guard is dead weight it can't detect. This drives
    it for real with the case the guard exists for — an address whose country and region
    FK disagree (bad import, or a customer editing country after picking a state). The
    Lagos option is priced in NGN for a Lagos courier; reaching it from Germany would
    both mis-price and mis-route the order."""
    _clear_seeded_options()
    zz = Country.objects.get(code="ZZ")
    lagos, ikeja, _eti = _lagos_tree()
    ng_opt = DeliveryOption.objects.create(
        name="Lagos Delivery", kind="manual", price=Decimal("1500.00"),
        currency=Currency.objects.get(code="NGN"), min_days=1, max_days=2,
    )
    ng_opt.regions.add(lagos)

    # country_code says DE (-> resolves to ZZ) but the region FKs still point at Lagos.
    addr = FakeAddress("DE", state_region=lagos, area_region=ikeja)
    matched = options_for_address(addr, lines=[], subtotal=Decimal("0"), country=zz)

    assert matched == []
