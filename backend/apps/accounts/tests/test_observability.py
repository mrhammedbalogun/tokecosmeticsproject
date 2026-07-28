"""Security-event logging on the auth endpoints.

Until this slice there was NO logging configuration and no Sentry: a password
spray, a lockout wave, or a Turnstile outage would have been completely
invisible — the first signal would have been customer WhatsApp complaints.

Everything security-shaped logs to the ``apps.security`` logger so one grep
(`docker logs api | grep apps.security`) tells the whole story. Sentry rides on
top: its logging integration turns ERROR records into events and INFO/WARNING
records into breadcrumbs automatically once SENTRY_DSN is set.
"""
import logging

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

PW = "Str0ng!pass9"
LOGIN = "/api/v1/auth/token/"
RESET = "/api/v1/auth/password/reset/"


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(email="shopper@example.com", password=PW)


def test_failed_login_is_logged(user, caplog):
    with caplog.at_level(logging.INFO, logger="apps.security"):
        r = APIClient().post(LOGIN, {"email": user.email, "password": "bad"}, format="json")
    assert r.status_code == 401
    assert any(
        "login failed" in rec.message and user.email in rec.message
        for rec in caplog.records
    ), "a failed login must leave a security log line"


def test_successful_login_is_logged(user, caplog):
    with caplog.at_level(logging.INFO, logger="apps.security"):
        r = APIClient().post(LOGIN, {"email": user.email, "password": PW}, format="json")
    assert r.status_code == 200
    assert any(
        "login succeeded" in rec.message and user.email in rec.message
        for rec in caplog.records
    )


def test_throttled_request_is_logged_with_path(caplog):
    """The 429 is the only signal an abuser gets back (reset always 200s), which
    means it is also the only signal WE get — losing it means a spray or an
    email-bomb attempt never appears anywhere."""
    client = APIClient()
    with caplog.at_level(logging.WARNING, logger="apps.security"):
        for _ in range(6):  # password_reset_email is 5/hour
            client.post(RESET, {"email": "victim@example.com"}, format="json")
    throttle_lines = [rec for rec in caplog.records if "throttled" in rec.message]
    assert throttle_lines, "a 429 must leave a security log line"
    assert any("/auth/password/reset/" in rec.message for rec in throttle_lines)


def test_turnstile_rejection_is_logged(settings, caplog):
    settings.TURNSTILE_SECRET = "sk-test"
    with caplog.at_level(logging.INFO, logger="apps.accounts.turnstile"):
        r = APIClient().post(LOGIN, {"email": "a@b.com", "password": "x"}, format="json")
    assert r.status_code == 403
    assert any("turnstile" in rec.message for rec in caplog.records)
