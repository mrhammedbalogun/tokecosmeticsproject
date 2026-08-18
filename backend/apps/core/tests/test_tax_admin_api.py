"""Plan-37: the tax settings surface. Master switch + per-market knobs, Owner-only.

`settings.manage` on both endpoints for the same reason the payout account carries it:
these change what every customer PAYS, which is not an operational knob a Manager
should hold. The scope matrix itself is asserted in test_money_config_admin.py.
"""
import pytest
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.core.models import AuditLog, Country, StoreSettings

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


@pytest.fixture
def manager():
    c = APIClient()
    c.force_authenticate(user=staff_user(email="manager@toke.test", role="Manager"))
    return c


# ── master switch ──────────────────────────────────────────────────────────────────


def test_tax_settings_require_staff():
    assert APIClient().get("/api/v1/admin/tax/settings/").status_code in (401, 403)


def test_tax_settings_are_owner_only(manager):
    assert manager.get("/api/v1/admin/tax/settings/").status_code == 403
    assert manager.patch(
        "/api/v1/admin/tax/settings/", {"charge_tax": False}, format="json"
    ).status_code == 403


def test_the_master_switch_reads_and_flips(owner):
    # First GET creates the singleton with its default — no deploy step needed.
    response = owner.get("/api/v1/admin/tax/settings/")
    assert response.status_code == 200
    assert response.data == {"charge_tax": True}

    response = owner.patch("/api/v1/admin/tax/settings/", {"charge_tax": False}, format="json")
    assert response.status_code == 200
    assert StoreSettings.load().charge_tax is False


def test_flipping_the_master_switch_writes_an_audit_row(owner):
    owner.patch("/api/v1/admin/tax/settings/", {"charge_tax": False}, format="json")
    row = AuditLog.objects.order_by("-id").first()
    assert row is not None
    assert row.model_label == "core.storesettings"
    assert row.changes == {"charge_tax": False}


# ── per-market knobs ───────────────────────────────────────────────────────────────


def test_tax_countries_lists_every_market_default_first(owner):
    response = owner.get("/api/v1/admin/tax/countries/")
    assert response.status_code == 200
    codes = [row["code"] for row in response.data]
    assert codes[0] == "NG"        # the default market leads
    assert codes[-1] == "ZZ"       # rest-of-world trails
    assert set(codes) == {"NG", "GB", "US", "CA", "ZZ"}


def test_a_markets_knobs_can_be_tuned(owner):
    response = owner.patch(
        "/api/v1/admin/tax/countries/GB/",
        {"charge_tax": True, "tax_rate_percent": "20.00",
         "tax_applies_to_delivery": True, "tax_label": "VAT"},
        format="json",
    )
    assert response.status_code == 200, response.data
    gb = Country.objects.get(code="GB")
    assert gb.tax_applies_to_delivery is True
    assert str(gb.tax_rate_percent) == "20.00"


def test_identity_fields_are_read_only(owner):
    """PATCHing `code`/`name` must not rename a market — DRF ignores read-only keys."""
    owner.patch(
        "/api/v1/admin/tax/countries/NG/",
        {"code": "XX", "name": "Renamed", "charge_tax": False},
        format="json",
    )
    ng = Country.objects.get(code="NG")
    assert ng.name == "Nigeria" and ng.charge_tax is False
    assert not Country.objects.filter(code="XX").exists()


def test_a_rate_above_100_is_refused(owner):
    response = owner.patch(
        "/api/v1/admin/tax/countries/NG/", {"tax_rate_percent": "101.00"}, format="json"
    )
    assert response.status_code == 400
    assert "tax_rate_percent" in response.data


def test_a_blank_label_is_refused(owner):
    response = owner.patch(
        "/api/v1/admin/tax/countries/NG/", {"tax_label": "   "}, format="json"
    )
    assert response.status_code == 400
    assert "tax_label" in response.data


def test_markets_cannot_be_created_or_deleted_here(owner):
    assert owner.post(
        "/api/v1/admin/tax/countries/", {"code": "FR"}, format="json"
    ).status_code == 405
    assert owner.delete("/api/v1/admin/tax/countries/NG/").status_code == 405
