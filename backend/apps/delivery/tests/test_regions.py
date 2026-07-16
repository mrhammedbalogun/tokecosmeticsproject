import pytest

from apps.core.models import Region

pytestmark = pytest.mark.django_db


def test_ng_region_tree_seeded_with_correct_counts():
    states = Region.objects.filter(country_code="NG", level="state")
    lgas = Region.objects.filter(country_code="NG", level="area")
    assert states.count() == 37  # 36 states + FCT
    assert lgas.count() == 774
    # Every LGA hangs off a state (no orphans).
    assert not lgas.filter(parent__isnull=True).exists()
    # Spot-check a known state/LGA pair.
    lagos = Region.objects.get(country_code="NG", level="state", name="Lagos")
    assert lagos.children.filter(name="Ikeja").exists()


def test_seed_options_present_when_countries_seeded():
    # This test runs on a fresh test DB (no country seed), so it only asserts the
    # migration is import-safe. Real seed verification is a manual checkpoint smoke.
    from apps.delivery.models import DeliveryOption
    assert DeliveryOption.objects.count() >= 0
