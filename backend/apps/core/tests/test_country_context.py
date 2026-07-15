import pytest
from django.test import RequestFactory

from apps.core.country_context import resolve_country
from apps.core.middleware import CountryMiddleware


@pytest.mark.django_db
def test_resolve_country_header_missing_returns_default():
    assert resolve_country(None).code == "NG"
    assert resolve_country("").code == "NG"
    assert resolve_country("   ").code == "NG"


@pytest.mark.django_db
def test_resolve_country_known_header():
    assert resolve_country("GB").code == "GB"
    assert resolve_country("gb").code == "GB"  # case-insensitive


@pytest.mark.django_db
def test_resolve_country_unknown_header_returns_rest_of_world():
    assert resolve_country("XX").code == "ZZ"
    assert resolve_country("JP").code == "ZZ"  # real country, not an active market


@pytest.mark.django_db
def test_middleware_attaches_request_country():
    mw = CountryMiddleware(lambda req: req)  # get_response echoes the request
    request = RequestFactory().get("/", HTTP_X_COUNTRY="GB")
    mw(request)
    assert request.country.code == "GB"

    request2 = RequestFactory().get("/")  # no header
    mw(request2)
    assert request2.country.code == "NG"
