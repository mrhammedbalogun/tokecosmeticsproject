"""The GIG coverage sync: per-StateId sweep, upsert, deactivate-never-delete,
auto-match that respects human-set mappings, and the nightly beat entry."""
import httpx
import pytest
import respx
from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings

from apps.core.models import Region
from apps.delivery.gig import client
from apps.delivery.gig.coverage import STATE_ID_MAX, sync_gig_coverage
from apps.delivery.models import GigLga

BASE = "https://gig.test"
SETTINGS = dict(GIG_BASE_URL=BASE, GIG_EMAIL="m@toke.test", GIG_PASSWORD="pw")

pytestmark = pytest.mark.django_db


def _envelope(rows):
    return {"message": "Success", "apiId": "a", "status": 200, "data": {"data": rows, "count": len(rows)}}


def _lga(state, lga, state_id, hd=False):
    return {"LGAState": state, "LGAName": lga, "StateId": state_id, "HomeDeliveryStatus": hd, "Status": True}


def _mock_sweeps(active_rows, home_rows):
    """Both endpoints answer per-StateId: rows whose StateId matches, else empty."""

    def _answer(rows):
        def _respond(request):
            state_id = int(request.url.params["StateId"])
            return httpx.Response(200, json=_envelope([r for r in rows if r["StateId"] == state_id]))

        return _respond

    respx.get(f"{BASE}/lga/active").mock(side_effect=_answer(active_rows))
    respx.get(f"{BASE}/homedelivery/active").mock(side_effect=_answer(home_rows))


@pytest.fixture(autouse=True)
def _token():
    cache.set(client.TOKEN_CACHE_KEY, "jwt", 300)
    yield
    cache.delete(client.TOKEN_CACHE_KEY)


@override_settings(**SETTINGS)
@respx.mock
def test_sync_upserts_flags_home_delivery_and_matches_regions():
    active = [_lga("Lagos", "Ikeja", 24, hd=True), _lga("Lagos", "Epe", 24), _lga("Adamawa", "Fufore", 2)]
    home = [_lga("Lagos", "Ikeja", 24, hd=True)]
    _mock_sweeps(active, home)

    counts = sync_gig_coverage()
    assert counts["active"] == 3
    assert counts["home_delivery"] == 1
    assert counts["created"] == 3
    assert counts["newly_matched"] == 3  # Ikeja + Epe exact; Fufore fuzzy -> Fufure

    ikeja = GigLga.objects.get(lga_name="Ikeja")
    assert ikeja.home_delivery and ikeja.is_active
    assert ikeja.region == Region.objects.get(
        country_code="NG", level="area", name="Ikeja", parent__name="Lagos"
    )
    assert GigLga.objects.get(lga_name="Fufore").region.name == "Fufure"
    assert not GigLga.objects.get(lga_name="Epe").home_delivery


@override_settings(**SETTINGS)
@respx.mock
def test_vanished_rows_deactivate_but_keep_their_mapping_and_human_edits_survive():
    _mock_sweeps([_lga("Lagos", "Ikeja", 24, hd=True), _lga("Lagos", "Epe", 24)], [])
    sync_gig_coverage()

    # A human re-points Epe at a deliberately different region.
    surulere = Region.objects.get(
        country_code="NG", level="area", name="Surulere Lagos State", parent__name="Lagos"
    )
    GigLga.objects.filter(lga_name="Epe").update(region=surulere)

    # Next sweep: Epe is gone from GIG's list.
    respx.reset()
    _mock_sweeps([_lga("Lagos", "Ikeja", 24, hd=True)], [])
    counts = sync_gig_coverage()

    epe = GigLga.objects.get(lga_name="Epe")
    assert counts["deactivated"] == 1
    assert not epe.is_active
    assert epe.region == surulere  # deactivation never touches the mapping
    assert GigLga.objects.get(lga_name="Ikeja").is_active

    # And when it returns, the row reactivates with the human mapping intact.
    respx.reset()
    _mock_sweeps([_lga("Lagos", "Ikeja", 24, hd=True), _lga("Lagos", "Epe", 24)], [])
    sync_gig_coverage()
    epe.refresh_from_db()
    assert epe.is_active and epe.region == surulere


@override_settings(**SETTINGS)
@respx.mock
def test_sweep_covers_the_full_state_id_range_and_command_reports_unmatched(capsys):
    _mock_sweeps([_lga("Lagos", "Atlantis West", 24)], [])
    from io import StringIO

    out = StringIO()
    call_command("sync_gig_coverage", stdout=out)
    text = out.getvalue()
    assert "UNMATCHED: Lagos / Atlantis West" in text
    assert "unmatched 1" in text
    # One request per StateId per endpoint — the validator allows no other filter.
    assert respx.get(f"{BASE}/lga/active").call_count == STATE_ID_MAX


def test_the_nightly_sync_is_scheduled():
    from django.conf import settings as dj

    tasks = {entry["task"] for entry in dj.CELERY_BEAT_SCHEDULE.values()}
    assert "apps.delivery.tasks.sync_gig_coverage_task" in tasks


@override_settings(**SETTINGS)
@respx.mock
def test_gig_outage_makes_the_task_a_noop_not_a_crash():
    respx.get(f"{BASE}/lga/active").mock(side_effect=httpx.ConnectError("down"))
    respx.get(f"{BASE}/homedelivery/active").mock(side_effect=httpx.ConnectError("down"))
    from apps.delivery.tasks import sync_gig_coverage_task

    result = sync_gig_coverage_task.apply().result  # eager, no broker
    assert "skipped" in result
    assert GigLga.objects.count() == 0
