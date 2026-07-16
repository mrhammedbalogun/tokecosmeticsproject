import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_meta_countries_lists_active_markets():
    r = APIClient().get("/api/v1/meta/countries/")
    assert r.status_code == 200
    codes = {c["code"] for c in r.data}
    assert {"NG", "GB", "US", "CA", "ZZ"} <= codes

    ng = next(c for c in r.data if c["code"] == "NG")
    assert ng["is_default"] is True
    assert ng["currency"]["code"] == "NGN"
    assert ng["currency"]["symbol"] == "₦"
    assert ng["tax_rate_percent"] == "7.50"


@pytest.mark.django_db
def test_meta_countries_excludes_inactive():
    from apps.core.models import Country

    Country.objects.filter(code="CA").update(is_active=False)
    r = APIClient().get("/api/v1/meta/countries/")
    codes = {c["code"] for c in r.data}
    assert "CA" not in codes


@pytest.mark.django_db
def test_meta_countries_is_public():
    # No Authorization header -> still 200 (storefront needs it pre-login).
    r = APIClient().get("/api/v1/meta/countries/")
    assert r.status_code == 200


def test_countries_endpoint_includes_area_label(db, client):
    # NG is seeded by migration 0003; set its area_label rather than re-create it.
    from apps.core.models import Country

    Country.objects.filter(code="NG").update(area_label="LGA")
    r = client.get("/api/v1/meta/countries/")
    ng = next(c for c in r.json() if c["code"] == "NG")
    assert ng["area_label"] == "LGA"
