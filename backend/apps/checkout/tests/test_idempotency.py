import pytest

from apps.checkout.services.idempotency import (
    IdempotencyConflict,
    IdempotencyKeyReused,
    begin,
    finish,
)

pytestmark = pytest.mark.django_db


def test_begin_then_finish_then_replay():
    ok = begin(user_id=1, key="abc", request_hash="h1")
    assert ok is None  # first call: proceed
    finish(user_id=1, key="abc", request_hash="h1", status_code=201, body={"order_number": "TC-100001"})
    replay = begin(user_id=1, key="abc", request_hash="h1")
    assert replay == (201, {"order_number": "TC-100001"})


def test_same_key_different_payload_rejected():
    begin(user_id=1, key="k2", request_hash="h1")
    finish(user_id=1, key="k2", request_hash="h1", status_code=201, body={"x": 1})
    with pytest.raises(IdempotencyKeyReused):
        begin(user_id=1, key="k2", request_hash="DIFFERENT")


def test_inflight_conflicts():
    begin(user_id=1, key="k3", request_hash="h1")  # marks in-progress, not finished
    with pytest.raises(IdempotencyConflict):
        begin(user_id=1, key="k3", request_hash="h1")
