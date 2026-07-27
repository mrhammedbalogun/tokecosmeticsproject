"""Password reset sends an EMAIL per request, to an address the caller chooses.

Unthrottled that is an email-bomb primitive: anyone can point it at a stranger's
inbox and let the global anon allowance (60/min) do the rest. It is also the
victim's mail provider, not ours, that decides we are the spammer.

The endpoint deliberately always returns 200 so it can't be used to enumerate
accounts (`views.py`: "Always 200 (don't leak which emails exist)"). That makes
throttling the ONLY signal an abuser gets, and the only defence available.

These tests run against the REAL configured rates (password_reset_email 5/hour,
password_reset_ip 60/hour, anon 60/min) in the style of test_auth_throttling.py:
pinning a fake rate would make the test a restatement of itself, not a check that
the configured protection actually bites.
"""
import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """Throttle counters live in the cache and would otherwise leak between tests."""
    cache.clear()
    yield
    cache.clear()


def test_password_reset_is_throttled_well_below_the_anon_allowance():
    """Repeatedly targeting ONE address trips the per-email window (5/hour), long
    before the 60/min anon allowance would have let an email-bomb through."""
    client = APIClient()
    codes = [
        client.post("/api/v1/auth/password/reset/", {"email": "victim@example.com"},
                    format="json").status_code
        for _ in range(6)
    ]
    assert codes.count(429) >= 1


def test_throttling_counts_requests_not_just_deliverable_emails():
    """The address does not have to exist, and rotating addresses must not help.
    A miss returns 200 exactly like a hit, and each fresh address gets a fresh
    per-email bucket — so the per-IP volume cap (60/hour) is what stops an
    unlimited probe. 61 distinct addresses from one IP must see a 429."""
    client = APIClient()
    codes = [
        client.post("/api/v1/auth/password/reset/", {"email": f"nobody{i}@example.com"},
                    format="json").status_code
        for i in range(61)
    ]
    assert codes.count(429) >= 1


def test_password_reset_confirm_is_throttled():
    """Reset-confirm has no bespoke throttle: its token is signed and not
    realistically brute-forceable. But it must not be EXEMPT — the global anon
    throttle (60/min) has to cover it like any other anonymous endpoint."""
    client = APIClient()
    codes = [
        client.post("/api/v1/auth/password/reset/confirm/",
                    {"uid": "x", "token": "y", "password": "Str0ngPassw0rd!"},
                    format="json").status_code
        for _ in range(61)
    ]
    assert codes.count(429) >= 1
