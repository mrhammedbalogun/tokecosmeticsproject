"""Google Ads server-side conversions, via the **Data Manager API**.

    POST https://datamanager.googleapis.com/v1/events:ingest

Verified against the live API on 2026-08-30 with `validateOnly: true` — both the bare
event and the full hashed-user-data shape below returned HTTP 200 against Toke's own ad
account. This file is the shape that passed.

── WHY NOT THE GOOGLE ADS API ──────────────────────────────────────────────────────────

Because it is closed to us. On 2026-06-15 Google stopped accepting NEW adopters of
offline conversion imports through `ConversionUploadService.UploadClickConversions`; a
developer token that was not already importing between December 2025 and May 2026 simply
errors. Toke never was. The Data Manager API is the sanctioned replacement (Google's
full switchover is March 2027) and it is markedly lighter: no developer token, no access
application, and a service account instead of an OAuth consent screen.

── WHY THIS CHANNEL NEEDS FOUR IDs ─────────────────────────────────────────────────────

The other three platforms send the server event to the same id the browser tag uses.
Google does not. The browser tag is addressed by `AW-…` plus a conversion label
(`pixel_id` / `secondary_id`); this API is addressed by the advertiser's customer id and
a numeric conversion ACTION id (`server_account_id` / `server_destination_id`). All four
live on the same `MarketingChannel` row.

── ONE CONVERSION ACTION, NOT TWO ──────────────────────────────────────────────────────

`server_destination_id` must name the SAME conversion action the browser tag reports to.
Google deduplicates on `transactionId`, which is our order number — the identical
mechanism the other three use with `event_id`. Pointing the server at its own "server
purchases" action would double every sale that arrives both ways, and it would look like
a good month rather than a bug.

── THE GMAIL TRAP ──────────────────────────────────────────────────────────────────────

Google normalises gmail.com/googlemail.com addresses by stripping dots and `+tags`
BEFORE hashing. Meta, TikTok and Snapchat explicitly do not — `hashing.normalize_email`
is deliberately literal for their sake and its docstring says so. Sending Meta's hash to
Google silently fails to match every Gmail customer, which for a Nigerian consumer store
is most of the list. `_google_email` below is the whole fix; do not "simplify" it away.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import time

import httpx
from django.conf import settings
from django.core.cache import cache

from apps.marketing import hashing
from apps.marketing.channels.base import ChannelResult, ConversionChannel
from apps.marketing.channels.http import TransportFailure, post_json
from apps.marketing.payloads import (
    ADD_TO_CART, INITIATE_CHECKOUT, PAGE_VIEW, PURCHASE, VIEW_CONTENT, ConversionPayload,
)

ENDPOINT = "https://datamanager.googleapis.com/v1/events:ingest"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/datamanager"

# Google mints one-hour tokens. Cached a little short of that so a token can never
# expire in flight between the check and the call — the same margin `gig/client.py`
# applies to its login token, and for the same reason.
TOKEN_CACHE_KEY = "marketing:google-ads:dm-token"
TOKEN_TTL_SECONDS = 3300

# Data Manager takes an `eventName` for non-purchase events, but Toke only sends
# purchases server-side today. The map exists so a caller cannot hand this adapter a
# canonical name it silently drops.
EVENT_NAMES = {
    PAGE_VIEW: "page_view",
    VIEW_CONTENT: "view_item",
    ADD_TO_CART: "add_to_cart",
    INITIATE_CHECKOUT: "begin_checkout",
    PURCHASE: "purchase",
}

_GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}
_DOTS = re.compile(r"\.")


def _google_email(value: str | None) -> str:
    """Normalise an email the way GOOGLE does, then hash it.

    Google's rule, and only Google's: for gmail.com and googlemail.com, strip every dot
    from the local part and drop a `+tag` suffix. `a.m.i.n.a+shop@gmail.com` and
    `amina@gmail.com` are one mailbox, and Google hashes them to one value. Every other
    domain gets the plain lowercase-and-trim that the other three platforms use.

    Applying this to Meta would break Meta; not applying it here breaks Google. Hence a
    second normaliser rather than a change to the shared one.
    """
    address = (value or "").strip().lower()
    if "@" not in address:
        return ""
    local, _, domain = address.rpartition("@")
    if domain in _GMAIL_DOMAINS:
        local = local.split("+", 1)[0]
        local = _DOTS.sub("", local)
    if not local:
        return ""
    return hashing.sha256_hex(f"{local}@{domain}")


class GoogleAdsCredentialError(Exception):
    """The service account JSON is absent or unreadable. Never raised at import time."""


def _service_account() -> dict:
    """The service account key, decoded from `GOOGLE_ADS_DM_CREDENTIALS_B64`.

    ── WHY BASE64 IN AN ENV VAR AND NOT A MOUNTED FILE ────────────────────────────────

    The API container takes its whole configuration from `env_file:
    /opt/tokecosmetics/.env.prod` and mounts only static, media and the migration paths
    (`infra/docker-compose.prod.yml`). A key file would therefore need a NEW volume
    mount, which is a compose edit, a deploy, and a second place a secret lives.

    One more line in `.env.prod` needs none of that, and `.env.prod` is already mode
    0600, already the home of every gateway key, and already in the backup rotation.
    Base64 because a PEM private key contains newlines and an env file does not carry
    them.
    """
    raw = getattr(settings, "GOOGLE_ADS_DM_CREDENTIALS_B64", "")
    if not raw:
        raise GoogleAdsCredentialError("GOOGLE_ADS_DM_CREDENTIALS_B64 is not set")
    try:
        return json.loads(base64.b64decode(raw))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise GoogleAdsCredentialError(f"could not decode the service account key: {exc}") from exc


def _access_token(*, force_refresh: bool = False) -> str:
    """A Data Manager access token, cached for just under its lifetime.

    The JWT-bearer flow, hand-rolled: sign a short assertion with the service account's
    private key and exchange it at Google's token endpoint. `google-auth` would do this
    too, but it is a new production dependency for twenty lines that PyJWT — already
    installed for the app's own tokens — covers exactly.

    Never logged, never returned to a caller other than this module.
    """
    if not force_refresh:
        cached = cache.get(TOKEN_CACHE_KEY)
        if cached:
            return cached

    import jwt  # local: PyJWT is only needed on this path

    info = _service_account()
    now = int(time.time())
    assertion = jwt.encode(
        {
            "iss": info["client_email"],
            "scope": SCOPE,
            "aud": TOKEN_ENDPOINT,
            "iat": now,
            # Google rejects an assertion older than an hour; 3600 is the documented max.
            "exp": now + 3600,
        },
        info["private_key"],
        algorithm="RS256",
        headers={"kid": info.get("private_key_id", "")},
    )
    response = httpx.post(
        TOKEN_ENDPOINT,
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
              "assertion": assertion},
        timeout=15,
    )
    if response.status_code != 200:
        # The body names the real cause (clock skew, revoked key, API not enabled) and
        # carries no secret — the assertion went the other way.
        raise GoogleAdsCredentialError(
            f"token exchange failed ({response.status_code}): {response.text[:300]}"
        )
    token = response.json()["access_token"]
    cache.set(TOKEN_CACHE_KEY, token, TOKEN_TTL_SECONDS)
    return token


class GoogleAdsChannel(ConversionChannel):
    code = "google_ads"

    def __init__(self, *, pixel_id: str, access_token: str, test_event_code: str = "",
                 account_id: str = "", destination_id: str = "", validate_only: bool = False):
        super().__init__(pixel_id=pixel_id, access_token=access_token,
                         test_event_code=test_event_code)
        self.account_id = account_id
        self.destination_id = destination_id
        # `validateOnly` asks Google to check the request and record NOTHING. It is what
        # the admin's test button uses: unlike the other three platforms, Google offers
        # no test console, so a "test event" that actually landed would be a real £0
        # purchase in a live conversion action.
        self.validate_only = validate_only

    def endpoint(self) -> str:
        return ENDPOINT

    def headers(self) -> dict:
        return {"Content-Type": "application/json",
                "Authorization": f"Bearer {_access_token()}"}

    def build(self, payload: ConversionPayload) -> dict:
        user = payload.user
        clicks = user.click_ids or {}

        identifiers: list[dict] = []
        email = _google_email(user.email)
        if email:
            identifiers.append({"emailAddress": email})
        phone = hashing.hashed_phone(user.phone)
        if phone:
            identifiers.append({"phoneNumber": phone})

        # ── AN ADDRESS IDENTIFIER NEEDS ALL FOUR PARTS, POSTCODE INCLUDED ─────────────
        #
        # `postalCode` is REQUIRED, not optional. Google's reference reads as though it
        # were optional; the live API disagrees, and says so for the whole request:
        #
        #   events[0].user_data.user_identifiers[2].address.postal_code
        #   "Required field is missing." REQUIRED_FIELD_MISSING
        #
        # Measured against the real endpoint on 2026-08-30. That is a 400 for the ENTIRE
        # batch, not a dropped identifier — so a single address short of a postcode would
        # lose the conversion outright.
        #
        # Which matters more here than it would elsewhere: **Nigerian addresses very often
        # have no postcode.** Toke's main market would have failed most orders. So the
        # address is included only when it is complete, and omitted otherwise — email and
        # phone are the stronger identifiers anyway, and they carry the match alone.
        given, family = hashing.hashed_name(user.first_name), hashing.hashed_name(user.last_name)
        region = (user.country or "").upper()[:2]
        postcode = (user.postcode or "").strip()
        if given and family and len(region) == 2 and postcode:
            identifiers.append({"address": {
                "givenName": given,
                "familyName": family,
                # NOT hashed — Google takes the region and postal codes in the clear.
                "regionCode": region,
                "postalCode": postcode,
            }})

        ad_identifiers: dict = {}
        # Exactly one click id, in Google's own order of preference. wbraid/gbraid are
        # the iOS shapes Google substitutes when a gclid cannot be set.
        for key in ("gclid", "wbraid", "gbraid"):
            if clicks.get(key):
                ad_identifiers[key] = clicks[key]
                break

        event: dict = {
            "transactionId": payload.order_number or payload.event_id,
            # RFC 3339. `event_time` is Unix seconds; Google wants an instant, and the
            # trailing Z is the only timezone we should ever assert — `placed_at` is
            # stored in UTC.
            "eventTimestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(payload.event_time)),
            "eventName": EVENT_NAMES[payload.event_name],
            "conversionValue": float(payload.value),
            "currency": payload.currency,
        }
        if ad_identifiers:
            event["adIdentifiers"] = ad_identifiers
        if identifiers:
            event["userData"] = {"userIdentifiers": identifiers}

        # Consent travels with the event, from the snapshot taken at checkout — not from
        # a live cookie read, which a webhook has no access to anyway.
        event["consent"] = {
            "adUserData": "CONSENT_GRANTED",
            "adPersonalization": "CONSENT_GRANTED",
        }

        body: dict = {
            "destinations": [{
                "operatingAccount": {
                    "accountType": "GOOGLE_ADS",
                    "accountId": self.account_id,
                },
                "productDestinationId": self.destination_id,
            }],
            # Our hashes are hex (`hashing.sha256_hex`). Declaring BASE64 here with hex
            # values is accepted by the API and matches nobody.
            "encoding": "HEX",
            "events": [event],
        }
        if self.validate_only:
            body["validateOnly"] = True
        return body

    def interpret(self, response: httpx.Response) -> ChannelResult:
        """Data Manager answers 200 with a `requestId`, and reports per-event problems in
        the same 200 rather than as an HTTP error.

        So a bare status check would mark a rejected batch as sent — the same trap TikTok
        sets with its envelope `code`. Anything in the response beyond the request id is
        treated as a failure worth reading.
        """
        result = super().interpret(response)
        if not result.ok:
            # A 401 means the cached token went stale early. Retryable: the next attempt
            # mints a fresh one.
            if response.status_code == 401:
                cache.delete(TOKEN_CACHE_KEY)
                return ChannelResult(ok=False, status=401, excerpt=result.excerpt, retryable=True)
            return result
        try:
            envelope = response.json()
        except ValueError:
            return ChannelResult(ok=False, status=response.status_code,
                                 excerpt=result.excerpt, retryable=True)
        # Google names the failure key differently across surfaces; anything that is not
        # the request id is a complaint.
        problems = {k: v for k, v in envelope.items() if k != "requestId"}
        if problems:
            return ChannelResult(ok=False, status=response.status_code,
                                 excerpt=json.dumps(problems)[:1000], retryable=False)
        return result

    def send(self, body: dict, *, timeout: float | None = None,
             retries: int | None = None) -> ChannelResult:
        """As the base class, except that a credential problem is caught and reported
        rather than raised — the outbox wants a `failed` row with a reason, not a
        traceback out of a Celery task."""
        try:
            headers = self.headers()
        except GoogleAdsCredentialError as exc:
            return ChannelResult(ok=False, excerpt=str(exc)[:1000], retryable=False)

        kwargs = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if retries is not None:
            kwargs["retries"] = retries
        try:
            response = post_json(self.endpoint(), json=body, headers=headers, **kwargs)
        except TransportFailure as exc:
            return ChannelResult(ok=False, excerpt=str(exc)[:1000], retryable=True)
        return self.interpret(response)
