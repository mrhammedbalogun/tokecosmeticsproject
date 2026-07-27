"""Password reset sends an EMAIL per request, to an address the caller chooses.

Unthrottled that is an email-bomb primitive: anyone can point it at a stranger's
inbox and let the global anon allowance (60/min) do the rest. It is also the
victim's mail provider, not ours, that decides we are the spammer.

The endpoint deliberately always returns 200 so it can't be used to enumerate
accounts (`views.py`: "Always 200 (don't leak which emails exist)"). That makes
throttling the ONLY signal an abuser gets, and the only defence available.

Reset-confirm is throttled too. Its token is a signed value and not realistically
brute-forceable, but rate-limiting it costs nothing and removes the question.
"""
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def _scoped(settings, scope: str, rate: str):
    """Pin the rate under test — reading whatever is configured makes the test a
    restatement of settings rather than a check on them."""
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {
            **settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], scope: rate,
        },
    }


def test_password_reset_is_throttled_well_below_the_anon_allowance(settings):
    _scoped(settings, "password_reset", "5/min")
    client = APIClient()
    codes = [
        client.post("/api/v1/auth/password/reset/", {"email": "victim@example.com"},
                    format="json").status_code
        for _ in range(6)
    ]
    assert codes.count(429) >= 1


def test_throttling_counts_requests_not_just_deliverable_emails(settings):
    """The address does not have to exist. A miss returns 200 exactly like a hit,
    so counting only real sends would leave the abuser an unlimited probe."""
    _scoped(settings, "password_reset", "5/min")
    client = APIClient()
    codes = [
        client.post("/api/v1/auth/password/reset/", {"email": f"nobody{i}@example.com"},
                    format="json").status_code
        for i in range(6)
    ]
    assert codes.count(429) >= 1


def test_password_reset_confirm_is_throttled(settings):
    _scoped(settings, "password_reset", "5/min")
    client = APIClient()
    codes = [
        client.post("/api/v1/auth/password/reset/confirm/",
                    {"uid": "x", "token": "y", "password": "Str0ngPassw0rd!"},
                    format="json").status_code
        for _ in range(6)
    ]
    assert codes.count(429) >= 1
