"""Test helpers for the store directory.

Plain functions rather than a `DjangoModelFactory`: every store needs a real
`Country` and a real `Region` from the seed migrations, and a factory that
invented them would build rows the public cascade can never find — the one thing
these tests exist to prove it does.
"""

from apps.core.models import Country, Region
from apps.stores.models import STORE_TYPE_DISTRIBUTOR, StoreLocation


def region(state: str, area: str | None = None, country_code: str = "NG") -> Region:
    """A seeded region by name. Raises if the seed does not have it, which is the
    right failure — a typo'd LGA name in a test would otherwise create a store
    nobody can search for and the assertion would be mysterious."""
    state_row = Region.objects.get(country_code=country_code, level="state", name=state)
    if area is None:
        return state_row
    return Region.objects.get(parent=state_row, level="area", name=area)


def store(
    name: str = "Beauty Hub",
    *,
    state: str = "Lagos",
    area: str | None = "Alimosho",
    country_code: str = "NG",
    **overrides,
) -> StoreLocation:
    defaults = {
        "name": name,
        "store_type": STORE_TYPE_DISTRIBUTOR,
        "country": Country.objects.get(code=country_code),
        "state_region": region(state, country_code=country_code),
        "area_region": region(state, area, country_code) if area else None,
        "address": "15 Example Street",
        "phone": "+2348000000000",
        "is_active": True,
    }
    defaults.update(overrides)
    return StoreLocation.objects.create(**defaults)
