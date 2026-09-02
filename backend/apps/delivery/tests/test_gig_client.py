"""The GIG client, against recorded sandbox behaviour (2026-08-02): single-nested
envelope, WAF-sensitive User-Agent, apiId on every envelope, JWT cached with one
auth-retry for reads and NONE when the caller forbids it (mutations)."""
import logging

import httpx
import pytest
import respx
from django.core.cache import cache
from django.test import override_settings

from apps.delivery.gig import client
from apps.delivery.gig.client import GigError, GigResponse, GigUnavailable, GigUpstream

BASE = "https://gig.test"

SETTINGS = dict(GIG_BASE_URL=BASE, GIG_EMAIL="merchant@toke.test", GIG_PASSWORD="pw")


def _envelope(data, status=200, message="Success", api_id="api-123"):
    return {"message": message, "apiId": api_id, "status": status, "data": data}


def _login_route(token="jwt-1"):
    return respx.post(f"{BASE}/login").mock(
        return_value=httpx.Response(200, json=_envelope({"access-token": token}))
    )


@pytest.fixture(autouse=True)
def _clean_token_cache():
    cache.delete(client.TOKEN_CACHE_KEY)
    yield
    cache.delete(client.TOKEN_CACHE_KEY)


@override_settings(**SETTINGS)
@respx.mock
def test_call_logs_in_once_caches_token_and_sends_user_agent():
    login = _login_route()
    route = respx.get(f"{BASE}/localstations/get").mock(
        return_value=httpx.Response(200, json=_envelope([{"StationId": 4}]))
    )
    first = client.call("GET", "/localstations/get")
    client.call("GET", "/localstations/get")  # second call: must reuse the token
    assert isinstance(first, GigResponse)
    assert first.data == [{"StationId": 4}]
    assert first.api_id == "api-123"
    assert login.call_count == 1  # token reused from cache
    req = route.calls[0].request
    assert req.headers["access-token"] == "jwt-1"
    # The WAF 403s library-default UAs — the explicit product UA must be on every request.
    assert req.headers["user-agent"] == client.USER_AGENT
    assert login.calls[0].request.headers["user-agent"] == client.USER_AGENT


@override_settings(**SETTINGS)
@respx.mock
def test_envelope_is_single_nested_and_errors_carry_api_id():
    _login_route()
    respx.post(f"{BASE}/price/v3").mock(
        return_value=httpx.Response(
            200, json=_envelope({}, status=400, message='"VehicleType" is not allowed', api_id="trace-9")
        )
    )
    with pytest.raises(GigError) as exc:
        client.call("POST", "/price/v3", json={})
    assert exc.value.status == 400
    assert exc.value.api_id == "trace-9"
    assert "VehicleType" in str(exc.value)


@override_settings(**SETTINGS)
@respx.mock
def test_auth_401_relogs_in_once_and_replays_for_reads():
    cache.set(client.TOKEN_CACHE_KEY, "stale-jwt", 300)
    login = _login_route(token="fresh-jwt")
    route = respx.get(f"{BASE}/lga/active").mock(
        side_effect=[
            httpx.Response(200, json=_envelope({}, status=401, message="Unauthorized")),
            httpx.Response(200, json=_envelope({"data": [], "count": 0})),
        ]
    )
    result = client.call("GET", "/lga/active")
    assert result.data == {"data": [], "count": 0}
    assert login.call_count == 1
    assert route.calls[1].request.headers["access-token"] == "fresh-jwt"


@override_settings(**SETTINGS)
@respx.mock
def test_retry_auth_false_never_replays_a_mutation():
    """GIG answers envelope-401 for BUSINESS failures too ("Shipment Details Not
    Found"), and a replayed capture would debit the wallet and dispatch a second
    rider. With retry_auth=False the 401 propagates untouched."""
    cache.set(client.TOKEN_CACHE_KEY, "jwt-1", 300)
    login = _login_route()
    route = respx.post(f"{BASE}/capture/preshipment").mock(
        return_value=httpx.Response(200, json=_envelope({}, status=401, message="Failure"))
    )
    with pytest.raises(GigError):
        client.call("POST", "/capture/preshipment", json={}, retry_auth=False, retries=0)
    assert route.call_count == 1
    assert login.call_count == 0


@override_settings(**SETTINGS)
@respx.mock
def test_connection_errors_retry_but_read_timeouts_never_do():
    cache.set(client.TOKEN_CACHE_KEY, "jwt-1", 300)
    calls = []

    def _flaky(req):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json=_envelope({"ok": True}))

    respx.get(f"{BASE}/companyDetails/get").mock(side_effect=_flaky)
    assert client.call("GET", "/companyDetails/get", sleep=lambda s: None).data == {"ok": True}
    assert len(calls) == 2

    timeout_route = respx.post(f"{BASE}/capture/preshipment").mock(
        side_effect=httpx.ReadTimeout("slow")
    )
    with pytest.raises(GigUnavailable):
        client.call("POST", "/capture/preshipment", json={}, retry_auth=False, sleep=lambda s: None)
    assert timeout_route.call_count == 1  # the server may have acted; never resent


@override_settings(**SETTINGS)
@respx.mock
def test_login_without_token_in_payload_is_an_error():
    respx.post(f"{BASE}/login").mock(return_value=httpx.Response(200, json=_envelope({})))
    with pytest.raises(GigError, match="no access-token"):
        client.login()


CDN_520 = (
    "<!DOCTYPE html><html><body><h1>Error 520</h1><p>The origin web server returned an "
    "invalid or incomplete response to Cloudflare. This typically indicates the origin "
    "is overloaded or misconfigured.</p></body></html>"
)


@override_settings(**SETTINGS)
@respx.mock
def test_an_answer_that_is_not_their_envelope_is_upstream_not_a_refusal(caplog):
    """Their CDN answering for them is not GIG refusing anything — and its prose about
    "the origin web server" must never become the sentence a Toke operator reads."""
    _login_route()
    respx.post(f"{BASE}/capture/preshipment").mock(
        return_value=httpx.Response(520, html=CDN_520)
    )
    with caplog.at_level(logging.WARNING, logger="apps.delivery.gig.client"):
        with pytest.raises(GigUpstream) as exc:
            client.call("POST", "/capture/preshipment", json={}, retry_auth=False, retries=0)

    assert exc.value.status == 520
    assert "520" in str(exc.value) and "/capture/preshipment" in str(exc.value)
    # Ours, not theirs: no CDN prose travels on the exception.
    assert "origin web server" not in str(exc.value)
    assert "Cloudflare" not in str(exc.value)
    # But it IS recoverable — the log is the only place the body survives.
    assert "origin web server" in caplog.text


@override_settings(**SETTINGS)
@respx.mock
def test_a_401_without_an_envelope_never_triggers_a_relogin_replay():
    """Re-login answers an expired token. A 401 page from their edge is not that, and
    replaying it would only repeat the request into the same wall."""
    cache.set(client.TOKEN_CACHE_KEY, "jwt-cached", 300)
    login = _login_route()
    route = respx.get(f"{BASE}/companyDetails/get").mock(
        return_value=httpx.Response(401, html="<html>401</html>")
    )
    with pytest.raises(GigUpstream):
        client.call("GET", "/companyDetails/get")
    assert route.call_count == 1
    assert login.call_count == 0  # the cached token was never thrown away
