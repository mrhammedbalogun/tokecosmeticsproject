"""The Google reviews header refresh: writes honest numbers on success, keeps
yesterday's numbers on ANY failure, and does nothing (not even an HTTP call)
when the key is unset."""
from decimal import Decimal

import httpx
import pytest
import respx
from django.test import override_settings

from apps.cms.google_reviews import refresh_reviews_meta
from apps.cms.models import GoogleReviewsMeta
from apps.cms.tasks import refresh_google_reviews_meta

pytestmark = pytest.mark.django_db

PLACE_URL = "https://places.googleapis.com/v1/places/pid-1"
SETTINGS = dict(GOOGLE_PLACES_API_KEY="server-key", GOOGLE_PLACE_ID="pid-1")


@override_settings(**SETTINGS)
@respx.mock
def test_success_updates_the_singleton_verbatim():
    GoogleReviewsMeta(rating=Decimal("5.0"), review_count_text="300+").save()
    route = respx.get(PLACE_URL).mock(
        return_value=httpx.Response(200, json={"rating": 4.6, "userRatingCount": 49})
    )
    result = refresh_reviews_meta()

    assert result == {"rating": "4.6", "count": 49}
    assert route.calls[0].request.headers["X-Goog-Api-Key"] == "server-key"
    meta = GoogleReviewsMeta.objects.get(pk=1)
    assert meta.rating == Decimal("4.6")
    assert meta.review_count_text == "49"  # honest count, not marketing text


@override_settings(**SETTINGS)
@respx.mock
def test_success_creates_the_singleton_when_missing():
    respx.get(PLACE_URL).mock(
        return_value=httpx.Response(200, json={"rating": 4.6, "userRatingCount": 49})
    )
    refresh_reviews_meta()
    assert GoogleReviewsMeta.objects.filter(pk=1).exists()


@override_settings(**SETTINGS)
@respx.mock
def test_http_error_and_empty_listing_keep_old_numbers():
    GoogleReviewsMeta(rating=Decimal("4.8"), review_count_text="300+").save()

    respx.get(PLACE_URL).mock(return_value=httpx.Response(403, json={"error": {}}))
    assert refresh_reviews_meta() == {"skipped": "HTTP 403"}

    # A listing with no reviews omits both fields — nothing truthful to write.
    respx.get(PLACE_URL).mock(return_value=httpx.Response(200, json={}))
    assert refresh_reviews_meta() == {"skipped": "no rating in response"}

    meta = GoogleReviewsMeta.objects.get(pk=1)
    assert meta.rating == Decimal("4.8")
    assert meta.review_count_text == "300+"


@override_settings(GOOGLE_PLACES_API_KEY="", GOOGLE_PLACE_ID="pid-1")
@respx.mock
def test_unset_key_skips_without_any_call():
    result = refresh_reviews_meta()
    assert "skipped" in result
    assert not respx.calls  # no HTTP attempted


@override_settings(**SETTINGS)
@respx.mock
def test_task_turns_transport_errors_into_a_skipped_pass():
    respx.get(PLACE_URL).mock(side_effect=httpx.ConnectError("down"))
    result = refresh_google_reviews_meta.apply().result
    assert "skipped" in result and "unreachable" in result["skipped"]
