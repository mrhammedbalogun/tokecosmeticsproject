import pytest
from rest_framework.test import APIClient

from apps.core.models import Region

pytestmark = pytest.mark.django_db


def test_states_then_lgas_browse():
    # Use a non-seeded country code so the child list is deterministic (the NG tree is
    # already seeded by migration 0002 with Lagos + its 20 real LGAs).
    lagos = Region.objects.create(country_code="XX", name="Lagos", level="state")
    Region.objects.create(country_code="XX", name="Ikeja", level="area", parent=lagos)
    client = APIClient()

    states = client.get("/api/v1/meta/regions/?country=XX")
    assert states.status_code == 200
    assert any(s["name"] == "Lagos" for s in states.data)

    lgas = client.get(f"/api/v1/meta/regions/?parent={lagos.id}")
    assert [r["name"] for r in lgas.data] == ["Ikeja"]


def test_regions_require_country_or_parent():
    r = APIClient().get("/api/v1/meta/regions/")
    assert r.status_code == 400
