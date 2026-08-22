"""The assumption the public URLs rest on: no two places in one scope slugify alike.

`/find-stores?state=lagos` resolves by comparing `slugify(Region.name)` against the
slug — there is no stored slug column and therefore no unique index to lean on.
That is a deliberate trade (see `services.resolve_region`), and this file is the
half of it that has to be executable: the day somebody seeds a region whose name
collides with an existing one, a customer's link silently resolves to the wrong
place, and this test says so first.
"""

from collections import Counter

import pytest

from apps.core.models import Country, Region
from apps.stores.normalize import slugify_name

pytestmark = pytest.mark.django_db


def _collisions(names) -> list[str]:
    counts = Counter(slugify_name(name) for name in names)
    return sorted(slug for slug, n in counts.items() if n > 1)


def test_no_two_countries_share_a_slug():
    names = Country.objects.filter(is_rest_of_world=False).values_list("name", flat=True)
    assert _collisions(names) == []


def test_no_two_states_in_one_country_share_a_slug():
    for code in Region.objects.values_list("country_code", flat=True).distinct():
        names = Region.objects.filter(country_code=code, level="state").values_list(
            "name", flat=True
        )
        assert _collisions(names) == [], f"{code} has colliding state slugs"


def test_no_two_areas_in_one_state_share_a_slug():
    for state in Region.objects.filter(level="state"):
        names = Region.objects.filter(parent=state, level="area").values_list(
            "name", flat=True
        )
        assert _collisions(names) == [], f"{state.name} has colliding area slugs"


def test_every_seeded_name_produces_a_non_empty_slug():
    """A name that slugifies to "" would be unaddressable — the resolver treats an
    empty slug as "not supplied" and would answer the wrong question entirely."""
    blank = [
        region.name
        for region in Region.objects.all().only("name")
        if not slugify_name(region.name)
    ]
    assert blank == []
