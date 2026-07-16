"""Tracking tokens. A token is a BEARER credential that lives in an inbox forever and
gets forwarded, so the tests here are mostly about what it must refuse to do."""
import pytest
from django.core import signing

from apps.orders.tokens import TrackingTokenError, make_tracking_token, read_tracking_token


def test_a_token_round_trips_to_its_order_number():
    token = make_tracking_token("TC-100001")

    assert read_tracking_token(token) == "TC-100001"


def test_a_token_for_one_order_does_not_open_another():
    """The URL carries the number too. Reading the number OUT of the token (rather than
    trusting the URL) is what stops TC-100001's token from opening TC-100002."""
    token = make_tracking_token("TC-100001")

    assert read_tracking_token(token) != "TC-100002"


def test_a_tampered_token_is_refused():
    token = make_tracking_token("TC-100001")
    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")

    with pytest.raises(TrackingTokenError):
        read_tracking_token(tampered)


def test_a_garbage_token_is_refused():
    with pytest.raises(TrackingTokenError):
        read_tracking_token("not-a-token")


def test_an_expired_token_is_refused():
    token = make_tracking_token("TC-100001")

    with pytest.raises(TrackingTokenError):
        read_tracking_token(token, max_age=-1)  # already past its life


def test_a_token_from_a_different_scope_is_refused():
    """Salts scope the signature. An invoice-scoped token must not open the tracking
    endpoint, so that adding a scope later can never silently widen an old token."""
    other = signing.dumps({"o": "TC-100001", "s": "invoice"}, salt="orders.invoice")

    with pytest.raises(TrackingTokenError):
        read_tracking_token(other)
