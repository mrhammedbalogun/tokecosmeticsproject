"""HTTP client for GIG Logistics' third-party API ("Agility Systems").

Everything here matches the API as MEASURED on the sandbox on 2026-08-02
(docs/gigimplementationresearch.md §2d) — GIG's published docs are wrong about
each of these:

- The response envelope is SINGLE-nested: `{message, apiId, status, data}`.
- Their WAF 403s library User-Agents (python-urllib, python-httpx defaults), so
  every request sends an explicit product UA.
- Validators are strict Joi: unknown fields are 400s, so callers must send exactly
  the shapes recorded in the research doc.
- The `apiId` in every envelope is GIG support's trace key. It is logged on every
  call, success or failure, and returned to callers who need to store it.

Auth: `POST /login` yields a JWT of UNDOCUMENTED lifetime, sent as an
`access-token` header. The token is cached; an auth-shaped 401 triggers one
re-login and one replay — but ONLY when the caller allows it. GIG also uses
envelope-status 401 for plain business failures ("Shipment Details Not Found"),
and replaying a mutating call after re-login would re-execute it. Money-moving
calls (waybill capture debits the wallet and dispatches a rider, irrevocably)
must pass `retry_auth=False, retries=0` and handle ambiguity themselves.

Transport policy mirrors payments/gateways/_http.py: retry only CONNECTION
errors (the request never reached the server); a read timeout or 5xx may have
already acted and is never retried here.

Their API sits behind a CDN (measured 2026-08-29: `server: cloudflare` in front
of an Express origin). When that CDN cannot get a clean response out of them it
answers for them, in HTML, about "the origin web server" — which is neither their
API speaking nor ours. Those answers raise `GigUpstream`, never a bare GigError:
the difference decides whether a capture is a safe retry or a money-ambiguity.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

USER_AGENT = "TokeCosmetics/1.0 (tokecosmetics.com; delivery integration)"
TOKEN_CACHE_KEY = "gig:access-token"
# JWT lifetime is undocumented; 4 hours forces a fresh login often enough that a
# quietly-expiring token costs at most one re-login, never a stream of 401s.
TOKEN_TTL_SECONDS = 4 * 60 * 60

DEFAULT_TIMEOUT = 15.0
DEFAULT_RETRIES = 2

_CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)


class GigError(Exception):
    """A response GIG itself produced: envelope status != 200, or transport-level
    4xx/5xx. Carries the envelope's message and apiId for GIG support."""

    def __init__(self, message: str, *, status: int | None = None, api_id: str = ""):
        super().__init__(message)
        self.status = status
        self.api_id = api_id


class GigUnavailable(GigError):
    """GIG could not be reached at all (connection failures, timeouts). For a
    quote this means "omit the option"; for a capture it means "unconfirmed —
    a human checks with GIG before anything is retried"."""


class GigUpstream(GigError):
    """GIG's edge answered; GIG's API did not. The body was not their envelope —
    an HTML error page from their CDN, or nothing at all.

    Separate from GigError because for a money-moving call the two mean opposite
    things. A GigError is their application's DECISION ("insufficient balance"):
    nothing was created, and a retry after fixing the cause is safe. This says
    only that their proxy could not read a clean response out of their origin —
    which their origin may well have produced AFTER doing the work. Ambiguous,
    exactly like a timeout, and handled the same way by capture.

    Its message is deliberately OURS, not theirs. What arrives in this case is a
    CDN's prose about "the origin web server", which — forwarded verbatim to the
    fulfilment desk, as this integration forwards every other GIG sentence —
    reads as if the Toke API were the broken one. Measured on TC-100147,
    2026-08-27: an operator spent three days believing our server was down.
    The body is logged instead, where it is a diagnostic rather than an accusation.
    """


@dataclass(frozen=True)
class GigResponse:
    data: Any
    api_id: str
    message: str


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
            raise GigUnavailable(f"{method} {url} timed out: {exc}") from exc
    raise GigUnavailable(f"{method} {url}: connection failed after {retries + 1} attempts: {last_exc}")


def _unwrap(response: httpx.Response, *, path: str) -> GigResponse:
    try:
        envelope = response.json()
    except ValueError as exc:
        # The body is read HERE or nowhere: it never travels with the exception (see
        # GigUpstream), and container logs die on the next deploy, so this line is the
        # one chance to see what their edge actually said. Capped, because a sustained
        # outage otherwise writes an HTML page per attempt into the log.
        logger.warning(
            "gig %s -> HTTP %s, no API envelope: %s",
            path, response.status_code, " ".join(response.text[:200].split()),
        )
        raise GigUpstream(
            f"GIG's platform answered HTTP {response.status_code} without an API "
            f"response for {path}",
            status=response.status_code,
        ) from exc
    api_id = str(envelope.get("apiId", ""))
    message = str(envelope.get("message", ""))
    status = envelope.get("status", response.status_code)
    logger.info("gig %s -> %s apiId=%s %s", path, status, api_id, message[:120])
    if response.status_code != 200 or status != 200:
        raise GigError(message or f"HTTP {response.status_code}", status=status, api_id=api_id)
    return GigResponse(data=envelope.get("data"), api_id=api_id, message=message)


def login() -> str:
    """Fresh login; caches and returns the token. Raises GigError on refusal."""
    result = _unwrap(
        _request(
            "POST",
            f"{settings.GIG_BASE_URL}/login",
            timeout=DEFAULT_TIMEOUT,
            retries=DEFAULT_RETRIES,
            json={"email": settings.GIG_EMAIL, "password": settings.GIG_PASSWORD},
            headers={"User-Agent": USER_AGENT},
        ),
        path="/login",
    )
    token = (result.data or {}).get("access-token", "")
    if not token:
        raise GigError("login succeeded but returned no access-token", api_id=result.api_id)
    cache.set(TOKEN_CACHE_KEY, token, TOKEN_TTL_SECONDS)
    return token


def _token() -> str:
    return cache.get(TOKEN_CACHE_KEY) or login()


def call(
    method: str,
    path: str,
    json: Any | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    retry_auth: bool = True,
    sleep=time.sleep,
) -> GigResponse:
    """One authenticated GIG call, unwrapped.

    `retry_auth=True` replays the request ONCE after a re-login if GIG answers
    401 — correct for reads and quotes, forbidden for mutations (see module
    docstring). Mutations pass `retry_auth=False, retries=0`.
    """
    token = _token()
    kwargs = {
        "headers": {"User-Agent": USER_AGENT, "access-token": token},
        **({"json": json} if json is not None else {}),
    }
    url = f"{settings.GIG_BASE_URL}{path}"
    try:
        return _unwrap(_request(method, url, timeout=timeout, retries=retries, sleep=sleep, **kwargs), path=path)
    except GigError as exc:
        # Only their API's OWN 401 envelope means "your token expired". A 401 that
        # arrived without an envelope came from their edge, not their auth layer, and
        # re-logging-in to replay it would just repeat the request into the same wall.
        if not (retry_auth and exc.status == 401
                and not isinstance(exc, (GigUnavailable, GigUpstream))):
            raise
        cache.delete(TOKEN_CACHE_KEY)
        kwargs["headers"]["access-token"] = login()
        return _unwrap(_request(method, url, timeout=timeout, retries=retries, sleep=sleep, **kwargs), path=path)
