import pytest

from apps.accounts.serializers import AddressSerializer
from apps.core.models import Region


@pytest.mark.django_db
def test_ng_address_requires_a_state_region():
    """NG is a region country: required_fields_for('NG') demands state_region."""
    s = AddressSerializer(data={
        "label": "Home", "first_name": "Ada", "phone": "+2348012345678",
        "line1": "1 Allen Ave", "country_code": "NG",
    })
    assert not s.is_valid()
    assert "state_region" in s.errors


@pytest.mark.django_db
def test_ng_address_with_valid_state_region_is_accepted():
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "+2348012345678", "line1": "1 Allen Ave",
        "country_code": "NG", "state_region": lagos.id,
    })
    assert s.is_valid(), s.errors


@pytest.mark.django_db
def test_ng_area_region_must_be_a_child_of_the_chosen_state():
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    abuja = Region.objects.create(country_code="NG", name="Abuja", level="state")
    garki = Region.objects.create(country_code="NG", name="Garki", level="area", parent=abuja)
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "+2348012345678", "line1": "1 Allen Ave",
        "country_code": "NG", "state_region": lagos.id, "area_region": garki.id,
    })
    assert not s.is_valid()
    assert "area_region" in s.errors


@pytest.mark.django_db
def test_state_region_must_be_in_the_declared_country():
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "+2348012345678", "line1": "1 Allen Ave",
        "country_code": "GB", "state_region": lagos.id,
    })
    assert not s.is_valid()
    assert "state_region" in s.errors


@pytest.mark.django_db
def test_gb_address_requires_a_postcode():
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "+447123456789", "line1": "1 Baker St",
        "country_code": "GB", "city_text": "London",
    })
    assert not s.is_valid()
    assert "postcode" in s.errors


@pytest.mark.django_db
def test_gb_address_with_state_city_and_postcode_is_accepted():
    england = Region.objects.create(country_code="GB", name="England", level="state")
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "+447123456789", "line1": "1 Baker St",
        "country_code": "GB", "state_region": england.id,
        "city_text": "London", "postcode": "NW1 6XE",
    })
    assert s.is_valid(), s.errors


@pytest.mark.django_db
def test_gb_address_requires_a_state_region_too():
    """GB is a region country since the Countries_breakdown work: a constituent-country
    FK is what lets a region-scoped delivery option match a GB address at all."""
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "+447123456789", "line1": "1 Baker St",
        "country_code": "GB", "city_text": "London", "postcode": "NW1 6XE",
    })
    assert not s.is_valid()
    assert "state_region" in s.errors


@pytest.mark.django_db
def test_a_new_ng_address_must_pick_an_lga_when_the_state_has_them():
    """The matcher and GIG quoting work on the area FK — "state only" quietly excludes
    the address from every LGA-scoped option, so a NEW address must finish the job."""
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    Region.objects.create(country_code="NG", name="Ikeja", level="area", parent=lagos)
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "+2348012345678", "line1": "1 Allen Ave",
        "country_code": "NG", "state_region": lagos.id,
    })
    assert not s.is_valid()
    assert "area_region" in s.errors


@pytest.mark.django_db
def test_unknown_country_needs_city_but_no_postcode():
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "+33612345678", "line1": "1 Rue",
        "country_code": "FR", "city_text": "Paris",
    })
    assert s.is_valid(), s.errors


# --- The pin (Plan-32b slice 3) ---

def _ng_lga():
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    ikeja = Region.objects.create(country_code="NG", name="Ikeja", level="area", parent=lagos)
    return lagos, ikeja


def _ng_payload(lagos, ikeja, **extra):
    return {
        "first_name": "Ada", "phone": "+2348012345678", "line1": "1 Allen Ave",
        "country_code": "NG", "state_region": lagos.id, "area_region": ikeja.id,
        **extra,
    }


@pytest.mark.django_db
def test_pin_round_trips_and_stays_optional():
    lagos, ikeja = _ng_lga()
    no_pin = AddressSerializer(data=_ng_payload(lagos, ikeja))
    assert no_pin.is_valid(), no_pin.errors  # null pin is normal and permanent

    s = AddressSerializer(data=_ng_payload(lagos, ikeja, latitude="6.618570", longitude="3.342590"))
    assert s.is_valid(), s.errors
    from django.contrib.auth import get_user_model
    addr = s.save(user=get_user_model().objects.create_user(email="pin@x.com", password="pw"))
    assert str(addr.latitude) == "6.618570"
    assert AddressSerializer(addr).data["longitude"] == "3.342590"


@pytest.mark.django_db
def test_half_a_pin_is_rejected_on_create_and_patch():
    lagos, ikeja = _ng_lga()
    s = AddressSerializer(data=_ng_payload(lagos, ikeja, latitude="6.618570"))
    assert not s.is_valid()
    assert "longitude" in s.errors

    # PATCH cannot strand one half either: clearing only the longitude of a
    # pinned address must fail against the merged values.
    from django.contrib.auth import get_user_model
    full = AddressSerializer(data=_ng_payload(lagos, ikeja, latitude="6.6", longitude="3.3"))
    assert full.is_valid(), full.errors
    addr = full.save(user=get_user_model().objects.create_user(email="pin2@x.com", password="pw"))
    patch = AddressSerializer(addr, data={"longitude": None}, partial=True)
    assert not patch.is_valid()
    assert "longitude" in patch.errors  # the error names the missing half
    # While clearing BOTH is a legitimate "remove my pin".
    clear = AddressSerializer(addr, data={"latitude": None, "longitude": None}, partial=True)
    assert clear.is_valid(), clear.errors


@pytest.mark.django_db
def test_pin_out_of_range_is_rejected():
    lagos, ikeja = _ng_lga()
    s = AddressSerializer(data=_ng_payload(lagos, ikeja, latitude="91", longitude="3.3"))
    assert not s.is_valid()
    assert "latitude" in s.errors


@pytest.mark.django_db
def test_address_phone_is_normalised_to_e164():
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "+234 801 234-5678", "line1": "1 Allen Ave",
        "country_code": "NG", "state_region": lagos.id,
    })
    assert s.is_valid(), s.errors
    assert s.validated_data["phone"] == "+2348012345678"


@pytest.mark.django_db
def test_address_phone_without_country_code_is_rejected():
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "08012345678", "line1": "1 Allen Ave",
        "country_code": "NG", "state_region": lagos.id,
    })
    assert not s.is_valid()
    assert "country code" in str(s.errors["phone"])


@pytest.mark.django_db
def test_address_patch_grandfathers_unchanged_legacy_phone(django_user_model):
    """A legacy national number re-submitted unchanged must not block an edit
    to some other field on an old address."""
    from apps.accounts.models import Address

    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 Rue", country_code="FR",
                                  city_text="Paris",
                                  first_name="Ada", phone="08012345678")
    s = AddressSerializer(instance=addr,
                          data={"label": "Home", "phone": "08012345678"}, partial=True)
    assert s.is_valid(), s.errors
    assert s.validated_data["phone"] == "08012345678"
