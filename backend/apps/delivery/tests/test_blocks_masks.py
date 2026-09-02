"""Plan-41: delivery blocks ("don't offer service X here") and fee masks (a
percentage on top of the real fee). Both act inside the one funnel every surface
reads — options_for_address / priced_options_for_address — so the options list,
the totals preview and place_order can never disagree about them.
"""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.core.models import Country, Currency, Region
from apps.delivery.carriers import priced_options_for_address
from apps.delivery.factories import DeliveryOptionFactory
from apps.delivery.models import (
    DeliveryBlock,
    DeliveryFeeMask,
    DeliveryPartner,
    PartnerZone,
)
from apps.delivery.services import apply_fee_mask, options_for_address

pytestmark = pytest.mark.django_db


class FakeAddress:
    """Duck-typed address: only the fields the matcher reads."""

    def __init__(self, country_code, state_region=None, area_region=None):
        self.country_code = country_code
        self.state_region = state_region
        self.area_region = area_region
        self.state_region_id = state_region.id if state_region else None
        self.latitude = None
        self.longitude = None


def _ng():
    ngn, _ = Currency.objects.get_or_create(code="NGN", defaults={"symbol": "₦"})
    ng, _ = Country.objects.get_or_create(
        code="NG", defaults={"name": "Nigeria", "currency": ngn, "is_default": True}
    )
    return ng


def _lagos_tree():
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


def _ogun_tree():
    ogun, _ = Region.objects.get_or_create(
        country_code="NG", name="Ogun", parent=None, defaults={"level": "state"}
    )
    abeokuta, _ = Region.objects.get_or_create(
        country_code="NG", name="Abeokuta South", parent=ogun, defaults={"level": "area"}
    )
    return ogun, abeokuta


def _ng_option(ng, name="Nationwide Standard", **over):
    opt = DeliveryOptionFactory(currency=ng.currency, name=name, **over)
    opt.countries.add(ng)
    return opt


def _names(address, ng):
    return [o["name"] for o in options_for_address(address, [], Decimal("0"), country=ng)]


def _partner(code="brandnpack"):
    from django.contrib.auth import get_user_model

    user, _ = get_user_model().objects.get_or_create(email=f"{code}@partner.test")
    partner, _ = DeliveryPartner.objects.get_or_create(
        code=code, defaults={"name": code.title(), "user": user}
    )
    return partner


# ---------------------------------------------------------------- blocks


def test_country_block_removes_the_service_everywhere_in_that_country():
    ng = _ng()
    lagos, ikeja, _ = _lagos_tree()
    opt = _ng_option(ng)
    DeliveryBlock.objects.create(service_code=f"option:{opt.pk}", country_code="NG")

    assert opt.name not in _names(FakeAddress("NG", lagos, ikeja), ng)
    assert opt.name not in _names(FakeAddress("NG"), ng)


def test_state_block_covers_every_lga_in_the_state_and_nothing_outside():
    ng = _ng()
    lagos, ikeja, _ = _lagos_tree()
    ogun, abeokuta = _ogun_tree()
    opt = _ng_option(ng)
    DeliveryBlock.objects.create(
        service_code=f"option:{opt.pk}", country_code="NG", state_region=lagos
    )

    assert opt.name not in _names(FakeAddress("NG", lagos, ikeja), ng)
    assert opt.name not in _names(FakeAddress("NG", lagos), ng)  # state, no LGA picked
    assert opt.name in _names(FakeAddress("NG", ogun, abeokuta), ng)


def test_lga_block_removes_only_that_lga():
    ng = _ng()
    lagos, ikeja, eti_osa = _lagos_tree()
    opt = _ng_option(ng)
    DeliveryBlock.objects.create(
        service_code=f"option:{opt.pk}", country_code="NG",
        state_region=lagos, area_region=ikeja,
    )

    assert opt.name not in _names(FakeAddress("NG", lagos, ikeja), ng)
    assert opt.name in _names(FakeAddress("NG", lagos, eti_osa), ng)


def test_a_block_names_one_service_not_the_address():
    """Blocking GIG in Ikeja must not touch the manual option serving Ikeja."""
    ng = _ng()
    lagos, ikeja, _ = _lagos_tree()
    manual = _ng_option(ng, name="Lagos Flat")
    gig = _ng_option(ng, name="GIG Door", kind="carrier", carrier_code="gig",
                     carrier_service="home")
    DeliveryBlock.objects.create(
        service_code="gig", country_code="NG", state_region=lagos, area_region=ikeja
    )

    names = _names(FakeAddress("NG", lagos, ikeja), ng)
    assert manual.name in names
    assert gig.name not in names


def test_partner_zone_rows_are_blocked_by_partner_code():
    ng = _ng()
    lagos, ikeja, _ = _lagos_tree()
    partner = _partner()
    PartnerZone.objects.create(
        partner=partner, lga_region=ikeja, lcda_name="Ikeja",
        areas_covered="Allen, Opebi", price=Decimal("3000"),
    )
    addr = FakeAddress("NG", lagos, ikeja)
    assert any(o["kind"] == "partner" for o in options_for_address(addr, [], Decimal("0"), ng))

    DeliveryBlock.objects.create(service_code=partner.code, country_code="NG",
                                 state_region=lagos)
    assert not any(
        o["kind"] == "partner" for o in options_for_address(addr, [], Decimal("0"), ng)
    )


def test_inactive_block_does_nothing():
    ng = _ng()
    lagos, ikeja, _ = _lagos_tree()
    opt = _ng_option(ng)
    DeliveryBlock.objects.create(
        service_code=f"option:{opt.pk}", country_code="NG", is_active=False
    )

    assert opt.name in _names(FakeAddress("NG", lagos, ikeja), ng)


# ---------------------------------------------------------------- masks


def test_mask_adds_the_percentage_to_a_manual_option():
    """The spec's own example: ₦5,000 masked 10% shows ₦5,500."""
    ng = _ng()
    opt = _ng_option(ng, price=Decimal("5000"))
    DeliveryFeeMask.objects.create(service_code=f"option:{opt.pk}", percent=Decimal("10"))

    (row,) = [
        o for o in options_for_address(FakeAddress("NG"), [], Decimal("0"), ng)
        if o["id"] == opt.pk
    ]
    assert row["price"] == "5500.00"


def test_mask_is_kobo_exact_half_up():
    assert apply_fee_mask(Decimal("4433.00"), Decimal("7.5")) == Decimal("4765.48")
    assert apply_fee_mask(Decimal("0.00"), Decimal("10")) == Decimal("0.00")
    assert apply_fee_mask(Decimal("5000.00"), None) == Decimal("5000.00")


def test_mask_names_one_service_and_inactive_masks_are_ignored():
    ng = _ng()
    masked = _ng_option(ng, name="Masked", price=Decimal("1000"))
    _ng_option(ng, name="Plain", price=Decimal("1000"))
    off = _ng_option(ng, name="Off", price=Decimal("1000"))
    DeliveryFeeMask.objects.create(service_code=f"option:{masked.pk}", percent=Decimal("10"))
    DeliveryFeeMask.objects.create(
        service_code=f"option:{off.pk}", percent=Decimal("50"), is_active=False
    )

    by_name = {
        o["name"]: o["price"]
        for o in options_for_address(FakeAddress("NG"), [], Decimal("0"), ng)
    }
    assert by_name["Masked"] == "1100.00"
    assert by_name["Plain"] == "1000.00"
    assert by_name["Off"] == "1000.00"


def test_mask_never_turns_free_over_back_into_a_charge():
    ng = _ng()
    opt = _ng_option(ng, price=Decimal("2000"), free_over=Decimal("50000"))
    DeliveryFeeMask.objects.create(service_code=f"option:{opt.pk}", percent=Decimal("10"))

    (row,) = [
        o for o in options_for_address(FakeAddress("NG"), [], Decimal("100000"), ng)
        if o["id"] == opt.pk
    ]
    assert row["price"] == "0.00"


def test_partner_zone_price_is_masked_by_partner_code():
    ng = _ng()
    lagos, ikeja, _ = _lagos_tree()
    partner = _partner()
    PartnerZone.objects.create(
        partner=partner, lga_region=ikeja, lcda_name="Testville",
        areas_covered="Allen, Opebi", price=Decimal("3000"),
    )
    DeliveryFeeMask.objects.create(service_code=partner.code, percent=Decimal("15"))

    addr = FakeAddress("NG", lagos, ikeja)
    (row,) = [
        o for o in options_for_address(addr, [], Decimal("0"), ng)
        if o["kind"] == "partner" and "Testville" in o["name"]
    ]
    assert row["price"] == "3450.00"


def test_gig_live_quote_is_masked_but_the_raw_quote_is_not(monkeypatch):
    """The customer pays the masked figure; the cached quote (what GigShipment.cost
    reconciles against) keeps GIG's real price."""
    ng = _ng()
    gig = _ng_option(ng, name="GIG Door", kind="carrier", carrier_code="gig",
                     carrier_service="home", price=Decimal("0"))
    DeliveryFeeMask.objects.create(service_code="gig", percent=Decimal("10"))

    class Quote:
        price = Decimal("5000.00")
        cache_key = "gig:quote:test"

    monkeypatch.setattr("apps.delivery.carriers.quote_home_delivery", lambda *a, **k: Quote())

    options = priced_options_for_address(FakeAddress("NG"), [], Decimal("0"), ng)
    (row,) = [o for o in options if o["id"] == gig.pk]
    assert row["price"] == "5500.00"
    assert row["carrier_quote_key"] == "gig:quote:test"


def test_a_blocked_gig_option_is_never_even_quoted(monkeypatch):
    ng = _ng()
    _ng_option(ng, name="GIG Door", kind="carrier", carrier_code="gig",
               carrier_service="home", price=Decimal("0"))
    DeliveryBlock.objects.create(service_code="gig", country_code="NG")

    def boom(*a, **k):  # pragma: no cover - the assertion IS that this never runs
        raise AssertionError("blocked carrier was quoted")

    monkeypatch.setattr("apps.delivery.carriers.quote_home_delivery", boom)

    names = [o["name"] for o in priced_options_for_address(FakeAddress("NG"), [], Decimal("0"), ng)]
    assert "GIG Door" not in names


# ------------------------------------------------- the public marketers' price list


def _rates_card(code):
    cards = APIClient().get("/api/v1/partner/rates/").data
    return next((c for c in cards if c["code"] == code), None)


def test_public_rates_show_the_masked_price():
    """The marketers' page must quote what the BUYER pays — its contract is zero
    drift from checkout, and checkout now charges the masked figure."""
    _ng()
    _, ikeja, _ = _lagos_tree()
    partner = _partner("testcourier")
    PartnerZone.objects.create(
        partner=partner, lga_region=ikeja, lcda_name="Testville",
        areas_covered="Allen", price=Decimal("5000"),
    )
    DeliveryFeeMask.objects.create(service_code="testcourier", percent=Decimal("10"))

    card = _rates_card("testcourier")
    assert [z["price"] for z in card["zones"]] == ["5500.00"]


def test_public_rates_hide_blocked_zones_at_every_rule_level():
    _ng()
    lagos, ikeja, eti_osa = _lagos_tree()
    partner = _partner("testcourier")
    PartnerZone.objects.create(
        partner=partner, lga_region=ikeja, lcda_name="Ikeja Row",
        areas_covered="Allen", price=Decimal("3000"),
    )
    PartnerZone.objects.create(
        partner=partner, lga_region=eti_osa, lcda_name="Eti-Osa Row",
        areas_covered="Lekki", price=Decimal("3500"),
    )

    # LGA rule: only that LGA's row disappears.
    rule = DeliveryBlock.objects.create(
        service_code="testcourier", country_code="NG",
        state_region=lagos, area_region=ikeja,
    )
    names = [z["lcda_name"] for z in _rates_card("testcourier")["zones"]]
    assert names == ["Eti-Osa Row"]

    # Whole-state rule: the partner's card vanishes from the page entirely.
    rule.area_region = None
    rule.save()
    assert _rates_card("testcourier") is None

    # A paused rule hides nothing.
    rule.is_active = False
    rule.save()
    assert len(_rates_card("testcourier")["zones"]) == 2


# ---------------------------------------------------------------- admin API


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def test_admin_endpoints_require_staff():
    anon = APIClient()
    for url in ("/api/v1/admin/delivery-blocks/", "/api/v1/admin/delivery-fee-masks/",
                "/api/v1/admin/delivery-services/"):
        assert anon.get(url).status_code in (401, 403)


def test_services_picker_lists_every_kind(client):
    ng = _ng()
    _partner()
    manual = _ng_option(ng, name="Lagos Flat")

    codes = {s["code"] for s in client.get("/api/v1/admin/delivery-services/").data}
    assert {"gig", "brandnpack", "store_pickup", f"option:{manual.pk}"} <= codes


def test_block_crud_and_validation(client):
    _ng()
    lagos, ikeja, _ = _lagos_tree()
    ogun, _ = _ogun_tree()

    created = client.post(
        "/api/v1/admin/delivery-blocks/",
        {"service_code": "gig", "country_code": "NG",
         "state_region": lagos.pk, "area_region": ikeja.pk},
        format="json",
    )
    assert created.status_code == 201, created.data
    assert created.data["service_name"] == "GIG Logistics"
    assert created.data["state_name"] == "Lagos"

    # A geographically impossible rule is refused, not silently never-matching.
    wrong_state = client.post(
        "/api/v1/admin/delivery-blocks/",
        {"service_code": "gig", "country_code": "NG",
         "state_region": ogun.pk, "area_region": ikeja.pk},
        format="json",
    )
    assert wrong_state.status_code == 400
    assert "area_region" in wrong_state.data

    unknown_service = client.post(
        "/api/v1/admin/delivery-blocks/",
        {"service_code": "dhl", "country_code": "NG"},
        format="json",
    )
    assert unknown_service.status_code == 400

    lga_without_state = client.post(
        "/api/v1/admin/delivery-blocks/",
        {"service_code": "gig", "country_code": "NG", "area_region": ikeja.pk},
        format="json",
    )
    assert lga_without_state.status_code == 400

    row_id = created.data["id"]
    assert client.patch(
        f"/api/v1/admin/delivery-blocks/{row_id}/", {"is_active": False}, format="json"
    ).status_code == 200
    assert client.delete(f"/api/v1/admin/delivery-blocks/{row_id}/").status_code == 204


def test_mask_crud_and_validation(client):
    created = client.post(
        "/api/v1/admin/delivery-fee-masks/",
        {"service_code": "gig", "percent": "10"},
        format="json",
    )
    assert created.status_code == 201, created.data

    duplicate = client.post(
        "/api/v1/admin/delivery-fee-masks/",
        {"service_code": "gig", "percent": "20"},
        format="json",
    )
    assert duplicate.status_code == 400  # one mask per service — edit the row instead

    typo_guard = client.post(
        "/api/v1/admin/delivery-fee-masks/",
        {"service_code": "store_pickup", "percent": "1000"},
        format="json",
    )
    assert typo_guard.status_code == 400

    row_id = created.data["id"]
    updated = client.patch(
        f"/api/v1/admin/delivery-fee-masks/{row_id}/", {"percent": "12.5"}, format="json"
    )
    assert updated.status_code == 200
    assert updated.data["percent"] == "12.50"
