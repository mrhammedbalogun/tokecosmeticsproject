"""Cloudflare Turnstile server-side verification for the public auth endpoints.

Canonical siteverify per developers.cloudflare.com/turnstile — POST the widget
token to Cloudflare and gate on ``success is True``, failing CLOSED on anything
else (network error, non-2xx, non-JSON). The widget token arrives from the
storefront BFF as ``turnstile_token`` in the JSON body (the BFF reads the
browser's ``cf-turnstile-response`` form field).

The staff login (``/auth/admin-token/``) is gated by the same function against a
possibly different secret — see ``admin_turnstile_secret``.

``remoteip`` is deliberately NOT sent: storefront traffic egresses from Vercel,
so the address Django sees is not the one that solved the challenge, and a
mismatched remoteip fails every legitimate customer. Add it only once the BFF
forwards the real client IP under a shared secret.
"""
import logging

import httpx
from django.conf import settings
from rest_framework.exceptions import PermissionDenied

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# One user-facing message for every rejection path. Distinguishing "missing"
# from "rejected" in the response would tell a bot author which hurdle they are
# failing; the machine-readable difference lives in the log lines instead.
_DENIED = "Human verification failed. Refresh the page and try again."


def admin_turnstile_secret() -> str:
    """The secret the STAFF gate verifies against: ``TURNSTILE_ADMIN_SECRET`` if set,
    otherwise the customer one.

    The fallback is what makes the setting optional. Turnstile widgets are
    domain-scoped and the admin app is a new hostname, so admin may need its own
    widget — but it does not need one to ship, and until the widget exists the admin
    gate should behave exactly like the customer gate rather than being silently off.
    The override also lets a Cloudflare-outage break-glass open one gate without
    opening both. See base.py for the full reasoning.
    """
    return settings.TURNSTILE_ADMIN_SECRET or settings.TURNSTILE_SECRET


def require_turnstile(request, secret: str | None = None) -> None:
    """Raise ``PermissionDenied`` (403) unless the request carries a token that
    Cloudflare confirms. No-op while the secret is unset — that is the rollout
    switch, not a bypass: see the setting's comment in base.py.

    ``secret`` defaults to ``TURNSTILE_SECRET`` (the customer gate). Callers that
    verify against a different widget pass it explicitly — a parameter rather than a
    second copy of this function, so there stays exactly ONE siteverify
    implementation and one fail-closed path to get right.
    """
    if secret is None:
        secret = settings.TURNSTILE_SECRET
    if not secret:
        return

    data = request.data
    token = data.get("turnstile_token") if hasattr(data, "get") else None
    if not isinstance(token, str) or not token:
        logger.info("turnstile: request without token on %s", request.path)
        raise PermissionDenied(_DENIED, code="turnstile_missing")

    try:
        response = httpx.post(
            SITEVERIFY_URL,
            data={"secret": secret, "response": token},
            timeout=5.0,
        )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Fail closed: an outage at Cloudflare must not become an open door for
        # credential stuffing. Turnstile outages are short; login pain is visible.
        logger.warning("turnstile: siteverify unavailable, failing closed: %s", exc)
        raise PermissionDenied(_DENIED, code="turnstile_unavailable")

    if result.get("success") is not True:
        logger.info(
            "turnstile: token rejected on %s: %s", request.path, result.get("error-codes")
        )
        raise PermissionDenied(_DENIED, code="turnstile_rejected")
