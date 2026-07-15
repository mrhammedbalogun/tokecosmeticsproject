import pytest

from apps.inventory.models import Warehouse


@pytest.mark.django_db
def test_warehouses_seeded():
    lagos = Warehouse.objects.get(name="Lagos HQ")
    assert lagos.location_country == "NG"
    assert set(lagos.serves_countries.values_list("code", flat=True)) == {"NG", "ZZ"}

    uk = Warehouse.objects.get(name="UK Warehouse")
    assert set(uk.serves_countries.values_list("code", flat=True)) == {"GB", "US", "CA", "ZZ"}
