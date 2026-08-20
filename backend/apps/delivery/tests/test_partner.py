"""Plan-39: the BrandnPack delivery partner — checkout expansion, the partner portal
API, the audience fences, and the staff admin surface."""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.core.models import Country, Region
from apps.delivery.models import DeliveryPartner, PartnerZone
from apps.delivery.services import option_id_matches, options_for_address

pytestmark = pytest.mark.django_db


class FakeAddress:
    def __init__(self, country_code, state_region=None, area_region=None):
        self.country_code = country_code
        self.state_region = state_region
        self.area_region = area_region


def _ng():
    return Country.objects.get(code="NG")


def _lagos_lga(name):
    lagos = Region.objects.get(country_code="NG", level="state", name="Lagos")
    return Region.objects.get(country_code="NG", level="area", parent=lagos, name=name)


def _partner():
    return DeliveryPartner.objects.get(code="brandnpack")


def _partner_rows(options):
    return [o for o in options if o["kind"] == "partner"]


# --- checkout expansion ---------------------------------------------------------


def test_every_lcda_row_of_the_lga_is_offered_with_the_docs_price_and_areas():
    """The ruling verbatim: don't disrupt the LGA structure — offer every LCDA row in
    the chosen LGA as its own option, labelled with the LCDA name."""
    ng = _ng()
    ikorodu = _lagos_lga("Ikorodu")
    addr = FakeAddress("NG", state_region=ikorodu.parent, area_region=ikorodu)

    rows = _partner_rows(options_for_address(addr, [], Decimal("0"), ng))

    assert len(rows) == 6  # the doc's six Ikorodu LCDAs
    central = next(r for r in rows if "Ikorodu Central" in r["name"])
    assert central["name"] == "Door Delivery - Ikorodu Central (BrandnPack)"
    assert central["price"] == "3000.00"
    assert central["areas_covered"] == "Ikorodu Town, Garage, Benson"
    assert central["id"].startswith("pz:")
    assert central["quote_required"] is False
    assert (central["min_days"], central["max_days"]) == (1, 3)


def test_unpriced_rows_never_reach_checkout():
    """Badagry arrived with no rates (Hammed: import inactive until the partner fills
    them) — a customer there sees no BrandnPack option, not a free one."""
    ng = _ng()
    badagry = _lagos_lga("Badagry")
    addr = FakeAddress("NG", state_region=badagry.parent, area_region=badagry)

    assert _partner_rows(options_for_address(addr, [], Decimal("0"), ng)) == []


def test_the_partner_kill_switch_removes_every_zone_at_once():
    ng = _ng()
    ikorodu = _lagos_lga("Ikorodu")
    addr = FakeAddress("NG", state_region=ikorodu.parent, area_region=ikorodu)
    DeliveryPartner.objects.filter(code="brandnpack").update(is_active=False)

    assert _partner_rows(options_for_address(addr, [], Decimal("0"), ng)) == []


def test_partner_options_only_ride_ngn_orders():
    """The zone table is implicitly NGN; a GB-context order over the same address must
    never have a naira figure added to its totals as if it were pounds."""
    gb = Country.objects.get(code="GB")
    ikorodu = _lagos_lga("Ikorodu")
    addr = FakeAddress("NG", state_region=ikorodu.parent, area_region=ikorodu)

    assert _partner_rows(options_for_address(addr, [], Decimal("0"), gb)) == []


def test_partner_options_ride_through_the_carrier_decorator_untouched():
    """kind="partner" is not kind="carrier": the GIG decorator must pass these rows
    through without trying to live-quote (or drop) them."""
    from apps.delivery.carriers import priced_options_for_address

    ng = _ng()
    ikorodu = _lagos_lga("Ikorodu")
    addr = FakeAddress("NG", state_region=ikorodu.parent, area_region=ikorodu)

    plain = _partner_rows(options_for_address(addr, [], Decimal("0"), ng))
    decorated = _partner_rows(priced_options_for_address(addr, [], Decimal("0"), ng))
    assert decorated == plain


def test_option_id_matching_folds_the_mixed_id_space():
    assert option_id_matches(3, "3")
    assert option_id_matches(3, 3)
    assert option_id_matches("pz:7", "pz:7")
    assert not option_id_matches("pz:7", "7")
    assert not option_id_matches(3, None)


# --- partner login + audience fences ---------------------------------------------


def _login(client=None, email="partner-brandnpack@tokecosmetics.com", password="pw"):
    return (client or APIClient()).post(
        "/api/v1/partner/auth/login/", {"email": email, "password": password},
        format="json",
    )


@pytest.fixture
def partner_with_password():
    partner = _partner()
    partner.user.set_password("pw")
    partner.user.save(update_fields=["password"])
    return partner


def test_login_mints_a_partner_pair(partner_with_password):
    response = _login()
    assert response.status_code == 200, response.data
    assert set(response.data) == {"access", "refresh", "partner"}
    assert response.data["partner"] == {"name": "BrandnPack", "code": "brandnpack"}


def test_login_refuses_a_wrong_password_and_a_switched_off_partner(partner_with_password):
    assert _login(password="nope").status_code == 401
    DeliveryPartner.objects.filter(code="brandnpack").update(is_active=False)
    assert _login().status_code == 401  # same generic refusal — no oracle


def test_a_customer_password_cannot_open_the_partner_door(django_user_model):
    django_user_model.objects.create_user(email="cust@x.com", password="pw")
    assert _login(email="cust@x.com").status_code == 401


def test_the_partner_token_opens_the_portal_and_nothing_else(partner_with_password):
    token = _login().data["access"]
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    assert client.get("/api/v1/partner/me/").status_code == 200
    # Customer surface: CustomerJWTAuthentication refuses the partner audience.
    assert client.get("/api/v1/auth/me/").status_code == 401
    # Admin surface: the audience equality check refuses it before permissions run.
    assert client.get("/api/v1/admin/delivery-options/").status_code == 401


def test_customer_and_staff_tokens_cannot_open_the_portal(django_user_model):
    user = django_user_model.objects.create_user(email="cust2@x.com", password="pw")
    customer_token = APIClient().post(
        "/api/v1/auth/token/", {"email": user.email, "password": "pw"}, format="json"
    ).data["access"]
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {customer_token}")
    assert client.get("/api/v1/partner/me/").status_code == 401


def test_the_kill_switch_revokes_outstanding_tokens_immediately(partner_with_password):
    token = _login().data["access"]
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    DeliveryPartner.objects.filter(code="brandnpack").update(is_active=False)

    assert client.get("/api/v1/partner/zones/").status_code == 403


# --- the portal's zone CRUD -------------------------------------------------------


@pytest.fixture
def portal(partner_with_password):
    client = APIClient()
    client.force_authenticate(user=partner_with_password.user)
    return client


def test_the_partner_sees_their_whole_card_and_only_their_card(portal):
    response = portal.get("/api/v1/partner/zones/")
    assert response.status_code == 200
    assert len(response.data) == 55  # the seeded doc, unpaginated


def test_adding_pricing_and_deleting_a_zone(portal):
    epe = _lagos_lga("Epe")
    created = portal.post("/api/v1/partner/zones/", {
        "lga_region": epe.id, "lcda_name": "Epe Waterfront",
        "areas_covered": "Marina, Jubilee Bridge", "dispatch_zone": "Zone 2",
        "price": "8000",
    }, format="json")
    assert created.status_code == 201, created.data
    zone_id = created.data["id"]
    assert created.data["lga_name"] == "Epe"

    patched = portal.patch(
        f"/api/v1/partner/zones/{zone_id}/", {"price": "8500"}, format="json"
    )
    assert patched.status_code == 200
    assert PartnerZone.objects.get(pk=zone_id).price == Decimal("8500")

    assert portal.delete(f"/api/v1/partner/zones/{zone_id}/").status_code == 204


def test_a_state_level_region_is_refused(portal):
    lagos = Region.objects.get(country_code="NG", level="state", name="Lagos")
    response = portal.post("/api/v1/partner/zones/", {
        "lga_region": lagos.id, "lcda_name": "All Lagos", "areas_covered": "Everywhere",
    }, format="json")
    assert response.status_code == 400


def test_a_zero_price_is_refused(portal):
    """No approval step means the serializer is the only thing between a typo and
    free delivery at checkout."""
    zone = PartnerZone.objects.filter(price__isnull=False).first()
    response = portal.patch(
        f"/api/v1/partner/zones/{zone.pk}/", {"price": "0"}, format="json"
    )
    assert response.status_code == 400


def test_the_lga_dropdown_serves_the_20_lagos_lgas(portal):
    response = portal.get("/api/v1/partner/lgas/")
    assert response.status_code == 200
    assert len(response.data) == 20


# --- staff admin surface -----------------------------------------------------------


@pytest.fixture
def owner_client():
    client = APIClient()
    client.force_authenticate(user=staff_user())
    return client


def test_partner_admin_requires_auth():
    assert APIClient().get("/api/v1/admin/partners/").status_code in (401, 403)


def test_staff_set_the_portal_password(owner_client):
    partner = _partner()
    assert not partner.user.has_usable_password()

    listed = owner_client.get("/api/v1/admin/partners/")
    assert listed.status_code == 200
    row = listed.data[0]
    assert row["has_password"] is False
    assert row["zone_count"] == 55 and row["live_zone_count"] == 47

    weak = owner_client.post(
        f"/api/v1/admin/partners/{partner.pk}/password/", {"password": "short"},
        format="json",
    )
    assert weak.status_code == 400

    ok = owner_client.post(
        f"/api/v1/admin/partners/{partner.pk}/password/",
        {"password": "brandnpack-rates-2026!"}, format="json",
    )
    assert ok.status_code == 200
    partner.user.refresh_from_db()
    assert partner.user.check_password("brandnpack-rates-2026!")


def test_staff_fix_a_rate_and_hide_a_row(owner_client):
    zone = PartnerZone.objects.filter(price__isnull=False).first()
    response = owner_client.patch(
        f"/api/v1/admin/partner-zones/{zone.pk}/",
        {"price": "4500", "is_active": False}, format="json",
    )
    assert response.status_code == 200, response.data
    zone.refresh_from_db()
    assert zone.price == Decimal("4500") and zone.is_active is False


def test_partner_create_via_api_stays_closed(owner_client):
    response = owner_client.post("/api/v1/admin/partners/", {"name": "X"}, format="json")
    assert response.status_code == 405
