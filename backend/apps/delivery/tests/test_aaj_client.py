"""The AAJ client, against recorded sandbox behaviour (2026-08-23): static Bearer
key, `{success,data,status,message}` envelope judged by `success` (a 500 can carry a
business refusal), list-shaped validation messages flattened, connection errors
retried and read timeouts never."""
import httpx
import pytest
import respx
from django.test import override_settings

from apps.delivery.aaj import client
from apps.delivery.aaj.client import AajError, AajResponse, AajUnavailable
from apps.delivery.aaj.states import STATE_CODES, canonical_state, state_code

BASE = "https://aaj.test/api/v2"
SETTINGS = dict(AAJ_BASE_URL=BASE, AAJ_API_KEY="aaj-testkey")


def _envelope(data, success=True, status=200, message="success!"):
    return {"success": success, "data": data, "status": status, "message": message,
            "timestamp": "2026-08-23T15:00:00.000Z"}


@override_settings(**SETTINGS)
@respx.mock
def test_call_sends_bearer_key_and_product_ua_and_unwraps_data():
    route = respx.get(f"{BASE}/partner/booking/get-categories").mock(
        return_value=httpx.Response(200, json=_envelope({"payload": [{"_id": "c1"}]}))
    )
    result = client.call("GET", "/partner/booking/get-categories")
    assert isinstance(result, AajResponse)
    assert result.data == {"payload": [{"_id": "c1"}]}
    assert result.status == 200
    req = route.calls[0].request
    assert req.headers["Authorization"] == "Bearer aaj-testkey"
    assert req.headers["User-Agent"].startswith("TokeCosmetics/")


@override_settings(**SETTINGS)
@respx.mock
def test_business_refusal_on_http_500_is_an_aaj_error_with_the_message():
    # MEASURED: process-booking answered HTTP 500 with success:false and the real
    # reason in `message` — the envelope is judged, not the transport code.
    respx.post(f"{BASE}/partner/booking/process-booking/b1").mock(
        return_value=httpx.Response(500, json={
            "success": False, "message": "Credit facility cannot be charged",
            "error": "BadRequestException", "status": 500,
        })
    )
    with pytest.raises(AajError) as exc:
        client.call("POST", "/partner/booking/process-booking/b1", retries=0)
    assert "Credit facility cannot be charged" in str(exc.value)
    assert exc.value.status == 500
    assert not isinstance(exc.value, AajUnavailable)


@override_settings(**SETTINGS)
@respx.mock
def test_list_shaped_validation_messages_are_flattened():
    respx.post(f"{BASE}/partner/booking/create-booking").mock(
        return_value=httpx.Response(400, json={
            "success": False, "error": "BadRequest", "status": 400,
            "message": ["receiver.contact.name - Name can only contain letters and spaces",
                        "receiver.contact.email - Required"],
        })
    )
    with pytest.raises(AajError) as exc:
        client.call("POST", "/partner/booking/create-booking", {}, retries=0)
    assert "letters and spaces" in str(exc.value) and "email - Required" in str(exc.value)


@override_settings(**SETTINGS)
@respx.mock
def test_success_false_on_http_200_is_still_an_error():
    respx.get(f"{BASE}/partner/booking/get-booking/x").mock(
        return_value=httpx.Response(200, json=_envelope(None, success=False, status=404,
                                                        message="Booking not found"))
    )
    with pytest.raises(AajError) as exc:
        client.call("GET", "/partner/booking/get-booking/x")
    assert exc.value.status == 404


@override_settings(**SETTINGS)
@respx.mock
def test_connection_errors_retry_with_backoff_then_unavailable():
    route = respx.get(f"{BASE}/quote").mock(side_effect=httpx.ConnectError("refused"))
    sleeps = []
    with pytest.raises(AajUnavailable):
        client.call("GET", "/quote", retries=2, sleep=sleeps.append)
    assert route.call_count == 3
    assert sleeps == [0.5, 1.0]


@override_settings(**SETTINGS)
@respx.mock
def test_read_timeout_is_never_retried():
    route = respx.post(f"{BASE}/partner/booking/process-booking/b1").mock(
        side_effect=httpx.ReadTimeout("slow")
    )
    with pytest.raises(AajUnavailable):
        client.call("POST", "/partner/booking/process-booking/b1", retries=2)
    assert route.call_count == 1


@override_settings(AAJ_BASE_URL=BASE, AAJ_API_KEY="")
def test_missing_key_refuses_before_any_http():
    with pytest.raises(AajError):
        client.call("GET", "/quote")


@override_settings(**SETTINGS)
@respx.mock
def test_non_json_body_is_an_error():
    respx.get(f"{BASE}/quote").mock(return_value=httpx.Response(502, text="<html>bad gateway"))
    with pytest.raises(AajError) as exc:
        client.call("GET", "/quote", retries=0)
    assert exc.value.status == 502


# --- states.py: the money-bearing code table -------------------------------------

def test_state_table_covers_every_seeded_ng_state():
    import json
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[2] / "core" / "fixtures" / "ng_regions.json"
    ours = set(json.loads(fixture.read_text()).keys())
    assert ours == set(STATE_CODES)


@pytest.mark.parametrize("name,code", [
    ("Lagos", "LA"), ("Lagos State", "LA"), ("lagos", "LA"),
    ("Federal Capital Territory", "FCT"), ("FCT", "FCT"), ("Abuja", "FCT"), ("Fct", "FCT"),
    ("Nasarawa", "NA"), ("Nassarawa", "NA"),
    ("Akwa ibom", "AK"), ("Cross river", "CR"), ("Kano", "KN"),
])
def test_state_code_accepts_our_names_and_known_aliases(name, code):
    assert state_code(name) == code


@pytest.mark.parametrize("name", ["", None, "Xyzzy", "Lagos Island", "Town"])
def test_state_code_never_guesses(name):
    # MEASURED: an unknown code silently prices as Lagos at AAJ. None here means the
    # caller omits the option — the only safe answer.
    assert state_code(name) is None
    assert canonical_state(name) is None
