"""The Marketing screen's surface: scopes, seeding, and the secrets that must not leak."""
from __future__ import annotations

import httpx
import pytest
import respx
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.core.models import AuditLog
from apps.marketing.models import CHANNEL_CHOICES, MarketingChannel
from apps.marketing.tests.factories import channel, configure, enable_tracking

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


# ── access ──────────────────────────────────────────────────────────────────────────


def test_the_marketing_surface_requires_staff():
    for path in ("/api/v1/admin/marketing/settings/", "/api/v1/admin/marketing/channels/"):
        assert APIClient().get(path).status_code in (401, 403)


def test_marketing_is_owner_only(manager):
    """`settings.manage`, like the tax and payout screens. `consent_required_countries`
    is a legal position and a pixel id decides which ad account receives the shop's
    customer data."""
    assert manager.get("/api/v1/admin/marketing/settings/").status_code == 403
    assert manager.get("/api/v1/admin/marketing/channels/").status_code == 403


# ── channels ────────────────────────────────────────────────────────────────────────


def test_listing_seeds_a_row_for_every_platform_the_code_can_serve(owner):
    """Created on read rather than by a seed migration: a migration seeds the channels
    that existed the day it was written, and a fifth platform added later would simply
    not appear."""
    assert MarketingChannel.objects.count() == 0

    response = owner.get("/api/v1/admin/marketing/channels/")

    assert response.status_code == 200
    assert {row["code"] for row in response.data} == {code for code, _ in CHANNEL_CHOICES}


def test_instagram_is_not_a_channel(owner):
    """The most common misunderstanding about this app. Instagram ads optimise against
    the SAME Meta dataset as Facebook; a separate row would be one nothing reads."""
    codes = {row["code"] for row in owner.get("/api/v1/admin/marketing/channels/").data}
    assert "instagram" not in codes
    assert "meta" in codes


def test_the_screen_reports_credential_status_without_ever_serving_the_credential(
    owner, settings
):
    settings.META_CAPI_ACCESS_TOKEN = "SECRET-TOKEN-VALUE"
    channel("meta")

    row = next(r for r in owner.get("/api/v1/admin/marketing/channels/").data
               if r["code"] == "meta")

    assert row["credential_configured"] is True
    assert row["missing_settings"] == []
    assert "SECRET-TOKEN-VALUE" not in str(row), "a token must never reach a browser"
    assert "access_token" not in row


def test_a_missing_credential_names_the_variable_to_add(owner, settings):
    settings.TIKTOK_EVENTS_ACCESS_TOKEN = ""
    channel("tiktok")

    row = next(r for r in owner.get("/api/v1/admin/marketing/channels/").data
               if r["code"] == "tiktok")

    assert row["credential_configured"] is False
    # A variable NAME, not a value — that is what makes it publishable and useful.
    assert row["missing_settings"] == ["TIKTOK_EVENTS_ACCESS_TOKEN"]


def test_google_ads_now_declares_a_server_side_sender(owner):
    """Reversed in Plan-44b. It WAS browser-only, because uploading conversions meant the
    Google Ads API and its access application — a path that turned out to be closed to
    new adopters from 2026-06-15. The Data Manager API replaced it and needs no
    application at all."""
    row = next(r for r in owner.get("/api/v1/admin/marketing/channels/").data
               if r["code"] == "google_ads")
    assert row["has_server_side"] is True
    assert row["missing_settings"] in ([], ["GOOGLE_ADS_DM_CREDENTIALS_B64"])


def test_google_ads_carries_its_own_server_addressing(owner):
    """The only channel addressed differently by its two halves: `AW-…` plus a label for
    the browser tag, a customer id plus a conversion action id for the API."""
    owner.get("/api/v1/admin/marketing/channels/")  # seed

    response = owner.patch("/api/v1/admin/marketing/channels/google_ads/", {
        "server_account_id": "3352855298", "server_destination_id": "7577766208",
    }, format="json")

    assert response.status_code == 200
    assert response.data["server_account_id"] == "3352855298"
    assert response.data["server_destination_id"] == "7577766208"


def test_a_channel_is_edited_by_code_and_the_edit_is_audited(owner):
    owner.get("/api/v1/admin/marketing/channels/")  # seed

    response = owner.patch("/api/v1/admin/marketing/channels/meta/",
                           {"is_enabled": True, "pixel_id": "1234567890"}, format="json")

    assert response.status_code == 200
    assert MarketingChannel.objects.get(code="meta").pixel_id == "1234567890"
    row = AuditLog.objects.filter(model_label="marketing.marketingchannel").latest("created_at")
    assert row.changes["pixel_id"] == "1234567890"


def test_a_channel_can_never_be_created_or_deleted_from_the_screen(owner):
    owner.get("/api/v1/admin/marketing/channels/")
    assert owner.post("/api/v1/admin/marketing/channels/",
                      {"code": "pinterest"}, format="json").status_code in (403, 404, 405)
    assert owner.delete("/api/v1/admin/marketing/channels/meta/").status_code == 405


# ── settings ────────────────────────────────────────────────────────────────────────


def test_the_master_switch_reads_and_flips_and_is_audited(owner):
    assert owner.get("/api/v1/admin/marketing/settings/").data["tracking_enabled"] is True

    response = owner.patch("/api/v1/admin/marketing/settings/",
                           {"tracking_enabled": False}, format="json")

    assert response.status_code == 200 and response.data["tracking_enabled"] is False
    row = AuditLog.objects.filter(model_label="marketing.marketingsettings").latest("created_at")
    assert row.changes["tracking_enabled"] is False


def test_the_consent_country_list_is_validated_and_normalised(owner):
    response = owner.patch("/api/v1/admin/marketing/settings/",
                           {"consent_required_countries": ["gb", "IE", "gb"]}, format="json")
    assert response.data["consent_required_countries"] == ["GB", "IE"]

    bad = owner.patch("/api/v1/admin/marketing/settings/",
                      {"consent_required_countries": ["Nigeria"]}, format="json")
    assert bad.status_code == 400


def test_the_default_consent_list_covers_the_uk(owner):
    """The shop sells into GB, and a UK visitor needs consent BEFORE a tracking cookie
    is set, not an opt-out afterwards."""
    assert "GB" in owner.get("/api/v1/admin/marketing/settings/").data[
        "consent_required_countries"
    ]


# ── test event ──────────────────────────────────────────────────────────────────────


@respx.mock
def test_the_test_event_button_reports_success_and_whether_it_hit_the_live_dataset(
    owner, settings
):
    configure(settings, "meta")
    channel("meta", test_event_code="")
    route = respx.post("https://graph.facebook.com/v25.0/PIXEL123/events").mock(
        return_value=httpx.Response(200, json={"events_received": 1})
    )

    response = owner.post("/api/v1/admin/marketing/channels/meta/test-event/")

    assert route.called
    assert response.data["ok"] is True
    # Said out loud so the screen can warn: with no test code this landed live.
    assert response.data["used_test_event_code"] is False


def test_the_test_event_button_refuses_before_it_can_be_misread(owner, settings):
    settings.META_CAPI_ACCESS_TOKEN = ""
    channel("meta")

    response = owner.post("/api/v1/admin/marketing/channels/meta/test-event/")

    assert response.status_code == 400
    assert response.data["error"] == "missing_credential"


# ── the public config endpoint ──────────────────────────────────────────────────────


def test_the_storefront_gets_pixel_ids_and_never_anything_else(settings):
    settings.META_CAPI_ACCESS_TOKEN = "SECRET"
    enable_tracking()
    channel("meta", pixel_id="1234567890", test_event_code="TEST9")

    response = APIClient().get("/api/v1/marketing/config/")

    assert response.status_code == 200
    body = str(response.data)
    assert "1234567890" in body
    assert "SECRET" not in body and "TEST9" not in body


def test_a_channel_with_no_pixel_id_is_not_offered_to_the_browser():
    """A script tag that cannot work is how a broken setup gets mistaken for a
    working one."""
    enable_tracking()
    channel("meta", pixel_id="")

    assert APIClient().get("/api/v1/marketing/config/").data["channels"] == []


def test_the_master_switch_empties_the_public_config():
    enable_tracking(tracking_enabled=False)
    channel("meta", pixel_id="123")

    response = APIClient().get("/api/v1/marketing/config/")

    assert response.data["tracking_enabled"] is False
    assert response.data["channels"] == []


def test_a_server_only_channel_is_not_served_to_the_browser():
    enable_tracking()
    channel("meta", pixel_id="123", browser_enabled=False)

    assert APIClient().get("/api/v1/marketing/config/").data["channels"] == []
