"""`load_lga_centroids` against the REAL seeded region tree (the Plan-08 seed
migration ships all 774 NG LGAs into every test database) and the real bundled
CSV. That makes the headline assertion the guarantee that matters: every seeded
LGA gets a centroid — 774/774, with only the planted fake left over. Creating a
parallel mini-tree here would duplicate seeded states (NULL parents don't
collide on the unique constraint) and turn key collisions into iteration-order
luck, which is exactly how this test first failed."""
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command

from apps.core.models import Region


@pytest.fixture
def ng_tree(db):
    def lga(state, name):
        return Region.objects.get(country_code="NG", level="area", name=name, parent__name=state)

    lagos = Region.objects.get(country_code="NG", level="state", name="Lagos")
    return {
        "ikeja": lga("Lagos", "Ikeja"),          # exact (GeoNames "Ikeja"/"Lagos State")
        "makurdi": lga("Benue", "Makurdi"),      # suffix ("Makurdi Local Government Area")
        "fufure": lga("Adamawa", "Fufure"),      # fuzzy (GeoNames "Fufore")
        "surulere": lga("Lagos", "Surulere Lagos State"),  # our disambiguator stripped
        "oyo": lga("Oyo", "Oyo"),                # aliased (the seed's name for Oyo West)
        "ghost": Region.objects.create(country_code="NG", name="Atlantis", level="area", parent=lagos),
    }


def _run(**kwargs) -> str:
    out = StringIO()
    call_command("load_lga_centroids", stdout=out, **kwargs)
    return out.getvalue()


def test_every_seeded_lga_gets_a_centroid_and_ghosts_are_reported(ng_tree):
    output = _run()
    for r in ng_tree.values():
        r.refresh_from_db()
    assert ng_tree["ikeja"].latitude == Decimal("6.618570")
    assert ng_tree["ikeja"].longitude == Decimal("3.342590")
    for key in ("makurdi", "fufure", "surulere", "oyo"):
        assert ng_tree[key].latitude is not None, key
    # No row anywhere near "Atlantis": stays null and is named in the report.
    assert ng_tree["ghost"].latitude is None
    assert "NO CENTROID: Lagos / Atlantis" in output
    # The whole point: 774/774 seeded LGAs matched; only the planted fake is left.
    assert "LGAs without a centroid: 1" in output


def test_default_fills_nulls_only_and_force_overwrites(ng_tree):
    ng_tree["ikeja"].latitude = Decimal("1.000000")
    ng_tree["ikeja"].longitude = Decimal("1.000000")
    ng_tree["ikeja"].save(update_fields=["latitude", "longitude"])

    _run()
    ng_tree["ikeja"].refresh_from_db()
    assert ng_tree["ikeja"].latitude == Decimal("1.000000")  # untouched without --force

    _run(force=True)
    ng_tree["ikeja"].refresh_from_db()
    assert ng_tree["ikeja"].latitude == Decimal("6.618570")


def test_rerun_is_idempotent(ng_tree):
    first = _run()
    second = _run()
    assert "LGAs without a centroid: 1" in first
    assert "LGAs without a centroid: 1" in second
    assert "updated 0" in second  # everything already set; nothing rewritten
    ng_tree["ikeja"].refresh_from_db()
    assert ng_tree["ikeja"].latitude == Decimal("6.618570")
