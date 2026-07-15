import pytest

from apps.core.models import Redirect, Region, SiteSetting


@pytest.mark.django_db
def test_sitesetting_typed_get():
    SiteSetting.objects.create(key="free_ship_min", value="15000", value_type="int")
    assert SiteSetting.get_typed("free_ship_min") == 15000
    assert SiteSetting.get_typed("missing", default="d") == "d"


@pytest.mark.django_db
def test_sitesetting_bool_and_json():
    SiteSetting.objects.create(key="flag", value="true", value_type="bool")
    SiteSetting.objects.create(key="cfg", value='{"a": 1}', value_type="json")
    assert SiteSetting.get_typed("flag") is True
    assert SiteSetting.get_typed("cfg") == {"a": 1}


@pytest.mark.django_db
def test_redirect_defaults_301():
    r = Redirect.objects.create(old_path="/x/", new_path="/y")
    assert r.status_code == 301
    assert r.hits == 0


@pytest.mark.django_db
def test_region_tree_parenting():
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    ikeja = Region.objects.create(country_code="NG", name="Ikeja", level="area", parent=lagos)
    assert ikeja.parent == lagos
    assert list(lagos.children.all()) == [ikeja]
