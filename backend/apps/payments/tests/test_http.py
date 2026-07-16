"""The shared gateway HTTP helper: 15s timeout, retry x2 on CONNECTION errors only,
never on 5xx for money-moving calls (rely on gateway idempotency instead). Connection
failures that exhaust retries surface as GatewayTimeout."""
import httpx
import pytest
import respx

from apps.payments.gateways._http import request
from apps.payments.gateways.base import GatewayTimeout


def _noop_sleep(_seconds):
    pass


@respx.mock
def test_retries_on_connect_error_then_succeeds():
    calls = []

    def _side_effect(req):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json={"ok": True})

    respx.post("https://gw.test/pay").mock(side_effect=_side_effect)
    resp = request("POST", "https://gw.test/pay", sleep=_noop_sleep)
    assert resp.status_code == 200
    assert len(calls) == 3  # 1 initial + 2 retries


@respx.mock
def test_gives_up_after_retries_and_raises_gateway_timeout():
    route = respx.post("https://gw.test/pay").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(GatewayTimeout):
        request("POST", "https://gw.test/pay", sleep=_noop_sleep)
    assert route.call_count == 3  # 1 + 2 retries, then give up


@respx.mock
def test_does_not_retry_on_5xx():
    slept = []
    route = respx.post("https://gw.test/pay").mock(return_value=httpx.Response(502))
    resp = request("POST", "https://gw.test/pay", sleep=lambda s: slept.append(s))
    assert resp.status_code == 502
    assert route.call_count == 1  # 5xx returned to caller, never retried
    assert slept == []
