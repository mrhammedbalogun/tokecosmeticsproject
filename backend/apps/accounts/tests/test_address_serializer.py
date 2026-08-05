import pytest

from apps.accounts.serializers import AddressSerializer
from apps.core.models import Region


@pytest.mark.django_db
def test_ng_address_requires_a_state_region():
    """NG is a region country: required_fields_for('NG') demands state_region."""
    s = AddressSerializer(data={
        "label": "Home", "first_name": "Ada", "phone": "08012345678",
        "line1": "1 Allen Ave", "country_code": "NG",
    })
    assert not s.is_valid()
    assert "state_region" in s.errors


@pytest.mark.django_db
def test_ng_address_with_valid_state_region_is_accepted():
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "08012345678", "line1": "1 Allen Ave",
        "country_code": "NG", "state_region": lagos.id,
    })
    assert s.is_valid(), s.errors


@pytest.mark.django_db
def test_ng_area_region_must_be_a_child_of_the_chosen_state():
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    abuja = Region.objects.create(country_code="NG", name="Abuja", level="state")
    garki = Region.objects.create(country_code="NG", name="Garki", level="area", parent=abuja)
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "08012345678", "line1": "1 Allen Ave",
        "country_code": "NG", "state_region": lagos.id, "area_region": garki.id,
    })
    assert not s.is_valid()
    assert "area_region" in s.errors


@pytest.mark.django_db
def test_state_region_must_be_in_the_declared_country():
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "08012345678", "line1": "1 Allen Ave",
        "country_code": "GB", "state_region": lagos.id,
    })
    assert not s.is_valid()
    assert "state_region" in s.errors


@pytest.mark.django_db
def test_gb_address_requires_a_postcode():
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "07123456789", "line1": "1 Baker St",
        "country_code": "GB", "city_text": "London",
    })
    assert not s.is_valid()
    assert "postcode" in s.errors


@pytest.mark.django_db
def test_gb_address_with_state_city_and_postcode_is_accepted():
    england = Region.objects.create(country_code="GB", name="England", level="state")
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "07123456789", "line1": "1 Baker St",
        "country_code": "GB", "state_region": england.id,
        "city_text": "London", "postcode": "NW1 6XE",
    })
    assert s.is_valid(), s.errors


@pytest.mark.django_db
def test_gb_address_requires_a_state_region_too():
    """GB is a region country since the Countries_breakdown work: a constituent-country
    FK is what lets a region-scoped delivery option match a GB address at all."""
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "07123456789", "line1": "1 Baker St",
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
        "first_name": "Ada", "phone": "08012345678", "line1": "1 Allen Ave",
        "country_code": "NG", "state_region": lagos.id,
    })
    assert not s.is_valid()
    assert "area_region" in s.errors


@pytest.mark.django_db
def test_unknown_country_needs_city_but_no_postcode():
    s = AddressSerializer(data={
        "first_name": "Ada", "phone": "0600000000", "line1": "1 Rue",
        "country_code": "FR", "city_text": "Paris",
    })
    assert s.is_valid(), s.errors
