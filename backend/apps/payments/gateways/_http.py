"""Shared HTTP for the httpx-based gateways (Paystack, Flutterwave, PayPal).

Policy (Fable 5 ruling): 15s timeout; retry x2 with backoff on CONNECTION errors
ONLY. A 5xx from a money-moving endpoint is NOT retried here — an ambiguous 5xx might
mean the charge went through, so re-sending without a gateway-supported idempotency
key could double-charge. Adapters handle idempotency at the API level (Stripe
Idempotency-Key header, Paystack's own reference) and inspect the returned status code.

The retry loop is explicit (rather than httpx's transport-level retries) so it stays
testable under respx and boring to read. `sleep` is injectable for tests.
"""
from __future__ import annotations

import time

import httpx

from apps.payments.gateways.base import GatewayTimeout

# Connection-level failures — safe to retry (the request never reached the server,
# or the connection dropped before a response). Read timeouts are deliberately NOT
# here: a slow response may already have moved money.
_CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)

DEFAULT_TIMEOUT = 15.0
DEFAULT_RETRIES = 2


def request(
    method: str,
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    sleep=time.sleep,
    **kwargs,
) -> httpx.Response:
    """Make one HTTP request, retrying only on connection errors. Returns the response
    (including 4xx/5xx — the caller decides what a bad status means). Raises
    GatewayTimeout if connection errors exhaust the retry budget."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                return client.request(method, url, **kwargs)
        except _CONNECT_ERRORS as exc:
            last_exc = exc
            if attempt < retries:
                sleep(0.5 * (2**attempt))  # 0.5s, 1s backoff
    raise GatewayTimeout(f"{method} {url} failed after {retries} retries: {last_exc}") from last_exc
