import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.core.models import Region


def _client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


@pytest.mark.django_db
def test_create_and_list_own_addresses(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    # NG regions are seeded by migrations (incl. a "Lagos"), so a re-fetch by name is
    # ambiguous — capture the created instance directly.
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    c = _client(user)

    r = c.post("/api/v1/me/addresses/", {
        "label": "Home", "first_name": "Ada", "phone": "08012345678",
        "line1": "1 Allen Ave", "country_code": "NG", "state_region": lagos.id,
    }, format="json")
    assert r.status_code == 201

    lst = c.get("/api/v1/me/addresses/")
    assert lst.status_code == 200
    assert len(lst.data) == 1
    assert lst.data[0]["label"] == "Home"


@pytest.mark.django_db
def test_a_user_cannot_see_or_edit_another_users_address(django_user_model):
    owner = django_user_model.objects.create_user(email="owner@b.com", password="pw")
    other = django_user_model.objects.create_user(email="other@b.com", password="pw")
    addr = Address.objects.create(user=owner, line1="1 Allen", country_code="GB",
                                  city_text="London", postcode="NW1 6XE",
                                  first_name="A", phone="07")

    c = _client(other)
    assert c.get(f"/api/v1/me/addresses/{addr.id}/").status_code == 404
    assert c.delete(f"/api/v1/me/addresses/{addr.id}/").status_code == 404
    assert Address.objects.filter(id=addr.id).exists()


@pytest.mark.django_db
def test_set_default_shipping_is_exclusive(django_user_model):
    user = django_user_model.objects.create_user(email="a@b.com", password="pw")
    a = Address.objects.create(user=user, line1="1", country_code="GB", city_text="L",
                               postcode="N1", first_name="A", phone="07",
                               is_default_shipping=True)
    b = Address.objects.create(user=user, line1="2", country_code="GB", city_text="L",
                               postcode="N2", first_name="A", phone="07")
    c = _client(user)

    r = c.post(f"/api/v1/me/addresses/{b.id}/set-default-shipping/")
    assert r.status_code == 200

    a.refresh_from_db()
    b.refresh_from_db()
    assert b.is_default_shipping is True
    assert a.is_default_shipping is False      # the previous default was cleared


@pytest.mark.django_db
def test_addresses_require_auth():
    assert APIClient().get("/api/v1/me/addresses/").status_code in (401, 403)
