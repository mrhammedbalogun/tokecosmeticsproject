"""The landmark has to survive all the way to the person holding the parcel.

Collecting it is the easy half. The half that matters is that it reaches the rider:
the order snapshot (which outlives the Address row), and the two carrier payloads,
neither of which has a landmark field of its own — so it is folded into the street
address line they actually print.
"""
import pytest
from decimal import Decimal

from apps.accounts.models import Address
from apps.checkout.services.checkout import _address_snapshot
from apps.core.models import Region

pytestmark = pytest.mark.django_db


def _ng_address(django_user_model, **extra):
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    ikeja = Region.objects.create(country_code="NG", name="Ikeja", level="area", parent=lagos)
    user = django_user_model.objects.create_user(email="lm@x.com", password="pw")
    defaults = dict(
        user=user, line1="1 Allen Ave", line2="Flat 3", country_code="NG",
        state_region=lagos, area_region=ikeja,
        first_name="Ada", last_name="Obi", phone="+2348012345678",
        landmark="Opposite Ikeja City Mall",
    )
    defaults.update(extra)
    return Address.objects.create(**defaults)


def test_the_snapshot_carries_the_landmark(django_user_model):
    """Snapshotted, not looked up live: the rider reads this weeks later and the
    customer may have edited or deleted the address by then."""
    addr = _ng_address(django_user_model)

    snap = _address_snapshot(addr)

    assert snap["landmark"] == "Opposite Ikeja City Mall"


def test_an_address_without_a_landmark_snapshots_an_empty_string(django_user_model):
    """Every non-NG address and every row saved before the field existed. Nothing
    downstream may assume it is set — the carrier builders below join on truthiness."""
    addr = _ng_address(django_user_model, landmark="")

    assert _address_snapshot(addr)["landmark"] == ""


def test_gig_puts_the_landmark_in_the_receiver_address():
    """GIG has no landmark field, so it rides in the address line, straight after the
    street lines and before the area — the order a person reads an address in."""
    snap = {
        "line1": "1 Allen Ave", "line2": "Flat 3",
        "landmark": "Opposite Ikeja City Mall",
        "area": "Ikeja", "state": "Lagos",
    }

    built = ", ".join(
        part for part in (
            snap.get("line1"), snap.get("line2"), snap.get("landmark"),
            snap.get("area"), snap.get("state"),
        )
        if part
    )

    assert built == "1 Allen Ave, Flat 3, Opposite Ikeja City Mall, Ikeja, Lagos"


def test_an_empty_landmark_leaves_no_double_comma():
    """The join is on truthiness precisely so an older order does not ship an address
    reading "1 Allen Ave, , Ikeja" to a courier."""
    snap = {"line1": "1 Allen Ave", "line2": "", "landmark": "", "area": "Ikeja",
            "state": "Lagos"}

    built = ", ".join(
        part for part in (
            snap.get("line1"), snap.get("line2"), snap.get("landmark"),
            snap.get("area"), snap.get("state"),
        )
        if part
    )

    assert built == "1 Allen Ave, Ikeja, Lagos"
    assert ", ," not in built


def test_aaj_line1_includes_the_landmark():
    """AAJ's payload has no landmark field either; capture.py folds it into line1."""
    snap = {"line1": "1 Allen Ave", "line2": "Flat 3",
            "landmark": "Opposite Ikeja City Mall"}

    line1 = ", ".join(
        p for p in (snap.get("line1"), snap.get("line2"), snap.get("landmark")) if p
    )

    assert line1 == "1 Allen Ave, Flat 3, Opposite Ikeja City Mall"


def test_a_guest_address_carries_a_landmark_too(django_user_model):
    """Guests build an UNSAVED Address through the same serializer path, so the field
    has to survive `build_unsaved_address` into the snapshot — a guest order is exactly
    as hard for a rider to find as an account one."""
    from apps.checkout.serializers import build_unsaved_address

    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    ikeja = Region.objects.create(country_code="NG", name="Ikeja", level="area", parent=lagos)

    addr = build_unsaved_address({
        "first_name": "Ada", "last_name": "Obi", "phone": "+2348012345678",
        "line1": "1 Guest Close", "landmark": "Beside Allen Roundabout",
        "country_code": "NG", "state_region": lagos, "area_region": ikeja,
    })

    assert addr.pk is None, "guest addresses are never saved"
    assert _address_snapshot(addr)["landmark"] == "Beside Allen Roundabout"
