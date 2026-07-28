"""Cloudflare Turnstile gate on the public auth endpoints (login, register,
password-reset request).

The gate lives HERE, in Django, not in the storefront BFF: the API is reachable
directly, so a BFF-only check would be decorative. The BFF merely forwards the
widget token (`cf-turnstile-response`) as `turnstile_token` in the JSON body.

Enablement is by configuration: the gate is active iff `TURNSTILE_SECRET` is
non-empty. That is deliberate rollout order — the backend can deploy to
production BEFORE the storefront ships the widget, with the secret unset, and
the gate turns on only when both halves exist. The suite-wide default is OFF
(see conftest.py); each test here opts in explicitly.

Fail-closed is the load-bearing property: a siteverify outage must not become
an open door for credential stuffing. Cloudflare's siteverify is called with
secret+response only — NO remoteip — because storefront traffic egresses from
Vercel, so the IP Django sees is not the IP that solved the challenge, and a
mismatched remoteip would fail every legitimate customer. Revisit when the BFF
forwards the real client IP under a shared secret.
"""
import httpx
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

PW = "CorrectHorse9!"
SECRET = "turnstile-test-secret"
LOGIN = "/api/v1/auth/token/"
REGISTER = "/api/v1/auth/register/"
RESET = "/api/v1/auth/password/reset/"


@pytest.fixture
def enabled(settings):
    settings.TURNSTILE_SECRET = SECRET


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(email="shopper@example.com", password=PW)


class _Recorder:
    """Stands in for httpx.post; records the outgoing call, returns a canned reply."""

    def __init__(self, response=None, error=None):
        self.calls = []
        self.response = response
        self.error = error

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        return self.response


def _response(status, **kwargs):
    """A complete httpx.Response — without `request` attached, raise_for_status()
    raises RuntimeError instead of behaving like a real reply."""
    from apps.accounts.turnstile import SITEVERIFY_URL

    return httpx.Response(status, request=httpx.Request("POST", SITEVERIFY_URL), **kwargs)


def _siteverify(monkeypatch, *, success=True, status=200, error=None):
    recorder = _Recorder(response=_response(status, json={"success": success}), error=error)
    monkeypatch.setattr("apps.accounts.turnstile.httpx.post", recorder)
    return recorder


# --- gate disabled (the configured default until prod ships the widget) -------


def test_login_needs_no_token_while_gate_is_off(user):
    r = APIClient().post(LOGIN, {"email": user.email, "password": PW}, format="json")
    assert r.status_code == 200
    assert "access" in r.data


def test_register_and_reset_need_no_token_while_gate_is_off():
    c = APIClient()
    assert c.post(REGISTER, {"email": "new@example.com", "password": PW, "first_name": "N"},
                  format="json").status_code == 201
    assert c.post(RESET, {"email": "new@example.com"}, format="json").status_code == 200


# --- login ---------------------------------------------------------------------


def test_login_without_token_is_rejected_before_any_network_call(enabled, user, monkeypatch):
    recorder = _siteverify(monkeypatch)
    r = APIClient().post(LOGIN, {"email": user.email, "password": PW}, format="json")
    assert r.status_code == 403
    assert recorder.calls == []  # missing token short-circuits; no siteverify round-trip


def test_login_with_rejected_token_is_403(enabled, user, monkeypatch):
    _siteverify(monkeypatch, success=False)
    r = APIClient().post(
        LOGIN,
        {"email": user.email, "password": PW, "turnstile_token": "tok"},
        format="json",
    )
    assert r.status_code == 403


def test_login_with_valid_token_proceeds(enabled, user, monkeypatch):
    recorder = _siteverify(monkeypatch, success=True)
    r = APIClient().post(
        LOGIN,
        {"email": user.email, "password": PW, "turnstile_token": "tok"},
        format="json",
    )
    assert r.status_code == 200
    assert "access" in r.data
    # Canonical siteverify call: secret + response, form-encoded, and no remoteip
    # (see module docstring for why remoteip must stay out for now).
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["url"] == "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    assert call["data"] == {"secret": SECRET, "response": "tok"}


def test_wrong_password_with_valid_token_is_still_401(enabled, user, monkeypatch):
    """The gate composes with authentication, it does not replace it."""
    _siteverify(monkeypatch, success=True)
    r = APIClient().post(
        LOGIN,
        {"email": user.email, "password": "wrong", "turnstile_token": "tok"},
        format="json",
    )
    assert r.status_code == 401


# --- fail closed ----------------------------------------------------------------


def test_siteverify_network_error_fails_closed(enabled, user, monkeypatch):
    _siteverify(monkeypatch, error=httpx.ConnectError("boom"))
    r = APIClient().post(
        LOGIN,
        {"email": user.email, "password": PW, "turnstile_token": "tok"},
        format="json",
    )
    assert r.status_code == 403


def test_siteverify_5xx_fails_closed(enabled, user, monkeypatch):
    _siteverify(monkeypatch, success=True, status=502)
    r = APIClient().post(
        LOGIN,
        {"email": user.email, "password": PW, "turnstile_token": "tok"},
        format="json",
    )
    assert r.status_code == 403


def test_siteverify_non_json_body_fails_closed(enabled, user, monkeypatch):
    recorder = _Recorder(response=_response(200, text="<html>cf error page</html>"))
    monkeypatch.setattr("apps.accounts.turnstile.httpx.post", recorder)
    r = APIClient().post(
        LOGIN,
        {"email": user.email, "password": PW, "turnstile_token": "tok"},
        format="json",
    )
    assert r.status_code == 403


# --- register and password reset ------------------------------------------------


def test_register_is_gated(enabled, monkeypatch):
    _siteverify(monkeypatch, success=True)
    c = APIClient()
    assert c.post(REGISTER, {"email": "n@example.com", "password": PW, "first_name": "N"},
                  format="json").status_code == 403
    assert c.post(REGISTER, {"email": "n@example.com", "password": PW, "first_name": "N",
                             "turnstile_token": "tok"},
                  format="json").status_code == 201


def test_password_reset_is_gated(enabled, monkeypatch):
    _siteverify(monkeypatch, success=True)
    c = APIClient()
    assert c.post(RESET, {"email": "x@example.com"}, format="json").status_code == 403
    assert c.post(RESET, {"email": "x@example.com", "turnstile_token": "tok"},
                  format="json").status_code == 200
