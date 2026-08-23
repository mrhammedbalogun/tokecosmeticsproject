"""HTTP client for AAJ Express' partner API (Plan-43).

Everything here matches the API as MEASURED on the sandbox on 2026-08-23
(docs/superpowers/plans/2026-08-23-plan-43-aaj-express.md §2) — where the
published docs (docs.aajexpress.org) disagree, the measurement wins:

- Auth is a static Bearer API key (`Authorization: Bearer aaj-…`). No login call,
  no token lifetime, nothing to cache — and therefore no auth-retry logic at all.
  The KEY decides which AAJ partner account a booking lands on.
- The envelope is `{success, data, status, message, timestamp}`; failures carry
  `success:false` with the reason in `message` (a string, OR a list of strings on
  validation errors) and sometimes an `error` list. The HTTP status usually matches
  `status`, but a 500 can carry a business refusal ("Credit facility cannot be
  charged") — so the envelope is what is judged, never the transport code alone.
- There is NO trace id in responses (GIG's `apiId` has no analogue). The booking
  and tracking ids are the only keys AAJ support can look things up by.

Transport policy mirrors gig/client.py and payments/gateways/_http.py: retry only
CONNECTION errors (the request never reached the server); a read timeout or 5xx
may already have acted and is never retried here. The one money-moving call
(process-booking) passes `retries=0` and reconciles ambiguity itself (capture.py).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

USER_AGENT = "TokeCosmetics/1.0 (tokecosmetics.com; delivery integration)"
DEFAULT_TIMEOUT = 15.0
DEFAULT_RETRIES = 2

_CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)


class AajError(Exception):
    """A response AAJ itself produced: `success:false`, or transport-level 4xx/5xx.
    Carries the envelope's message (flattened to one string) and status."""

    def __init__(self, message: str, *, status: int | None = None, errors: Any = None):
        super().__init__(message)
        self.status = status
        self.errors = errors


class AajUnavailable(AajError):
    """AAJ could not be reached at all (connection failures, timeouts). For a
    quote this means "omit the option"; for process-booking it means "reconcile
    against get-booking before anything is retried"."""


@dataclass(frozen=True)
class AajResponse:
    data: Any
    message: str
    status: int


def _request(method: str, url: str, *, timeout: float, retries: int, sleep=time.sleep, **kwargs):
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                return client.request(method, url, **kwargs)
        except _CONNECT_ERRORS as exc:
            last_exc = exc
            if attempt < retries:
                sleep(0.5 * (2**attempt))
        except httpx.TimeoutException as exc:
            # Read/write/pool timeouts: the server may have acted. Never retried.
            raise AajUnavailable(f"{method} {url} timed out: {exc}") from exc
    raise AajUnavailable(f"{method} {url}: connection failed after {retries + 1} attempts: {last_exc}")


def _flatten_message(envelope: dict, http_status: int) -> str:
    raw = envelope.get("message")
    if isinstance(raw, list):
        return "; ".join(str(m) for m in raw) or f"HTTP {http_status}"
    if isinstance(raw, str) and raw:
        return raw
    err = envelope.get("error")
    if isinstance(err, str) and err:
        return err
    return f"HTTP {http_status}"


def _unwrap(response: httpx.Response, *, path: str) -> AajResponse:
    try:
        envelope = response.json()
    except ValueError as exc:
        raise AajError(
            f"AAJ returned non-JSON (HTTP {response.status_code}) for {path}",
            status=response.status_code,
        ) from exc
    if not isinstance(envelope, dict):
        raise AajError(f"AAJ returned an unexpected body for {path}", status=response.status_code)
    status = envelope.get("status", response.status_code)
    message = _flatten_message(envelope, response.status_code)
    logger.info("aaj %s -> %s %s", path, status, message[:120])
    if response.status_code >= 400 or envelope.get("success") is not True:
        raise AajError(message, status=status, errors=envelope.get("error"))
    return AajResponse(data=envelope.get("data"), message=message, status=int(status))


def call(
    method: str,
    path: str,
    json: Any | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    sleep=time.sleep,
) -> AajResponse:
    """One authenticated AAJ call, unwrapped. `path` is relative to AAJ_BASE_URL
    (which already ends in `/api/v2`): "/quote", "/partner/booking/create-booking"…

    Mutations that move money pass `retries=0` (see module docstring)."""
    if not settings.AAJ_API_KEY:
        raise AajError("AAJ_API_KEY is not configured")
    kwargs = {
        "headers": {
            "User-Agent": USER_AGENT,
            "Authorization": f"Bearer {settings.AAJ_API_KEY}",
        },
        **({"json": json} if json is not None else {}),
    }
    url = f"{settings.AAJ_BASE_URL.rstrip('/')}{path}"
    return _unwrap(
        _request(method, url, timeout=timeout, retries=retries, sleep=sleep, **kwargs),
        path=path,
    )
