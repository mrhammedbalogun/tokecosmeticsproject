"""HTTP for the conversion adapters, and why its retry policy is the OPPOSITE of the
payment gateways'.

`payments/gateways/_http.py` retries connection errors ONLY, and says why: a 5xx from a
money-moving endpoint might mean the charge went through, so re-sending could double-
charge. That reasoning does not transfer here, and copying it would be cargo-cult.

A conversion event is **idempotent at the vendor**. All four platforms dedupe on the
`event_id` we send, and we send the same one every time (the order number, for a
purchase). So a read timeout or a 502 that may or may not have landed is safe to send
again: the worst case is the vendor discarding the duplicate, which is what the id is
for. Losing the event, by contrast, permanently under-reports a sale.

Hence: retry connection errors AND read timeouts here, and let Celery retry the 5xx
after a longer backoff (`tasks.py`). Nothing in this module can move money or change an
order; the only thing at risk is a number in an ad dashboard.
"""
from __future__ import annotations

import time

import httpx

# Both are safe here, unlike in payments: the vendor deduplicates on event_id.
_RETRY_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout)

# Shorter than the payment gateways' 15s. A conversion event is never in front of a
# customer — nobody is waiting on it — but it DOES occupy a Celery worker, and four
# channels x a slow vendor is how a worker pool disappears during a sale.
DEFAULT_TIMEOUT = 10.0
DEFAULT_RETRIES = 1


class TransportFailure(Exception):
    """The request never got an answer. Always retryable."""


def post_json(
    url: str,
    *,
    json: dict,
    headers: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    sleep=time.sleep,
) -> httpx.Response:
    """POST JSON, retrying transport failures. Returns the response for ANY status —
    the adapter decides what the vendor meant."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                return client.post(url, json=json, headers=headers or {})
        except _RETRY_ERRORS as exc:
            last_exc = exc
            if attempt < retries:
                sleep(0.5 * (2**attempt))
    raise TransportFailure(f"POST {url} failed after {retries} retries: {last_exc}") from last_exc
