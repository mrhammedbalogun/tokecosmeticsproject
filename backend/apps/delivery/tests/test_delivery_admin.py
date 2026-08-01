"""Plan-19b: delivery-option field CRUD.

Flat fields only. Coverage (`countries`, `regions`) is read-only here and gets its own
screen in 19d — editing it means choosing among 811 regions, which is a different problem
from "the Lagos price went up", the edit an operator actually makes as costs move.
"""
import pytest
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.core.models import Currency
from apps.delivery.models import DeliveryOption

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


def _option(**over):
    defaults = {
        "name": "Lagos Delivery", "price": "1500", "currency": Currency.objects.first(),
        "min_days": 1, "max_days": 2,
    }
    return DeliveryOption.objects.create(**{**defaults, **over})


def test_requires_staff():
    assert APIClient().get("/api/v1/admin/delivery-options/").status_code in (401, 403)


def test_the_price_can_be_changed(client):
    """The whole point: fuel and logistics costs move, and this was a database edit."""
    option = _option()

    response = client.patch(
        f"/api/v1/admin/delivery-options/{option.pk}/", {"price": "2000"}, format="json"
    )

    assert response.status_code == 200, response.data
    option.refresh_from_db()
    assert str(option.price) == "2000.00"


def test_AN_IMPOSSIBLE_ETA_IS_REFUSED(client):
    """`min_days` above `max_days` renders as "3-1 days" on the storefront and reads as a
    bug in the shop rather than a typo in the admin."""
    option = _option()

    response = client.patch(
        f"/api/v1/admin/delivery-options/{option.pk}/",
        {"min_days": 5, "max_days": 2},
        format="json",
    )

    assert response.status_code == 400
    assert "min_days" in response.data


def test_coverage_is_reported_but_not_editable_here(client):
    option = _option()

    row = client.get(f"/api/v1/admin/delivery-options/{option.pk}/").data

    assert "country_codes" in row and "region_count" in row
    # Read-only: sending coverage here is ignored rather than half-applied, and 19d owns
    # the tree that can express it properly.
    client.patch(
        f"/api/v1/admin/delivery-options/{option.pk}/", {"country_codes": ["GB"]}, format="json"
    )
    assert list(option.countries.values_list("code", flat=True)) == []


def test_a_delivery_option_cannot_be_deleted(client):
    option = _option()

    assert client.delete(f"/api/v1/admin/delivery-options/{option.pk}/").status_code == 405
    assert DeliveryOption.objects.filter(pk=option.pk).exists()
