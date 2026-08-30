"""Meta Conversions API — Facebook AND Instagram.

    POST https://graph.facebook.com/{version}/{dataset_id}/events?access_token=...

Verified against Meta's own documentation on 2026-08-29. The facts that shape this file:

- Every hashed identifier is an **ARRAY**, even when there is one of them. A bare string
  is accepted by the endpoint and matches nothing.
- `em, ph, fn, ln, ct, st, zp, country, external_id` are SHA-256. `client_ip_address`,
  `client_user_agent`, `fbc` and `fbp` are RAW. Hashing the second group is the classic
  silent failure — no error, no match, no explanation.
- `event_time` is Unix SECONDS and may be up to **7 days** old. That is what makes the
  outbox safe: an event stuck behind a failing worker for an afternoon is still accepted.
- `value` is a JSON number here (Snapchat wants a string; do not share the code).

The Graph version is pinned in settings rather than hardcoded. Meta retires versions on
its own schedule, and the day one is retired the fix must be an env edit, not a release.
"""
from __future__ import annotations

import time

from django.conf import settings

from apps.marketing import hashing
from apps.marketing.channels.base import ConversionChannel
from apps.marketing.payloads import (
    ADD_TO_CART, INITIATE_CHECKOUT, PAGE_VIEW, PURCHASE, VIEW_CONTENT, ConversionPayload,
)

EVENT_NAMES = {
    PAGE_VIEW: "PageView",
    VIEW_CONTENT: "ViewContent",
    ADD_TO_CART: "AddToCart",
    INITIATE_CHECKOUT: "InitiateCheckout",
    PURCHASE: "Purchase",
}


def build_fbc(fbclid: str, clicked_at: int | None) -> str:
    """Meta's click-id cookie value, built from the `?fbclid=` we saw ourselves.

    Format: `fb.{subdomain_index}.{creation_time_ms}.{fbclid}`.

    WHY WE BUILD IT RATHER THAN ONLY READING THE COOKIE. `_fbc` is written by Meta's
    pixel JavaScript. An ad blocker, a locked-down browser, or a visitor who consented a
    beat after landing all mean the pixel never ran — and then the click that cost money
    is invisible to the server-side event too. Our proxy sees the `?fbclid=` on the
    landing navigation regardless, so we can reconstruct exactly what the pixel would
    have written. This is the single biggest match-quality win available to a
    server-side integration, and it costs one line of string formatting.

    `subdomain_index = 1` because the cookie belongs to `tokecosmetics.com` — the
    registrable domain (0 would be `com`, 2 would be `www.tokecosmetics.com`). It must
    match where the pixel would have set it, or the two values disagree for one visitor.

    A missing timestamp falls back to now. That is slightly wrong (the click happened
    earlier) and deliberately preferred to dropping the click id entirely: Meta uses the
    timestamp for ordering, not for attribution.
    """
    if not fbclid:
        return ""
    ms = int((clicked_at or time.time()) * 1000)
    return f"fb.1.{ms}.{fbclid}"


class MetaChannel(ConversionChannel):
    code = "meta"

    def endpoint(self) -> str:
        version = getattr(settings, "META_GRAPH_API_VERSION", "v25.0")
        return (
            f"https://graph.facebook.com/{version}/{self.pixel_id}/events"
            f"?access_token={self.access_token}"
        )

    def build(self, payload: ConversionPayload) -> dict:
        user = payload.user
        cookies = user.pixel_cookies or {}
        clicks = user.click_ids or {}

        # The pixel's own cookie wins when it exists: it is what the browser-side event
        # carried, and a mismatched pair is worse than either alone. Ours is the fallback
        # for every visitor whose pixel never ran — see build_fbc.
        fbc = cookies.get("fbc") or build_fbc(clicks.get("fbclid", ""), clicks.get("ts"))

        user_data: dict = {}
        # `_add` keeps empty identifiers OUT of the body entirely. Sending `"em": [""]`
        # asserts we know an email we do not have, and Meta scores it as a failed match
        # rather than an absent one.
        def _add(key: str, value: str, *, as_list: bool = True) -> None:
            if value:
                user_data[key] = [value] if as_list else value

        _add("em", hashing.hashed_email(user.email))
        _add("ph", hashing.hashed_phone(user.phone))
        _add("fn", hashing.hashed_name(user.first_name))
        _add("ln", hashing.hashed_name(user.last_name))
        _add("ct", hashing.hashed_city(user.city))
        _add("st", hashing.hashed_state(user.state))
        _add("zp", hashing.hashed_zip(user.postcode))
        _add("country", hashing.hashed_country(user.country))
        _add("external_id", hashing.sha256_hex(user.external_id))
        # RAW, all four. See the module docstring.
        _add("client_ip_address", user.client_ip, as_list=False)
        _add("client_user_agent", user.client_user_agent, as_list=False)
        _add("fbc", fbc, as_list=False)
        _add("fbp", cookies.get("fbp", ""), as_list=False)

        event: dict = {
            "event_name": EVENT_NAMES[payload.event_name],
            "event_time": payload.event_time,
            "event_id": payload.event_id,
            "action_source": "website",
            "user_data": user_data,
        }
        if payload.source_url:
            event["event_source_url"] = payload.source_url

        custom: dict = {}
        if payload.currency:
            custom["currency"] = payload.currency
            custom["value"] = float(payload.value)
        if payload.contents:
            custom["content_type"] = "product"
            custom["content_ids"] = [c.content_id for c in payload.contents]
            custom["contents"] = [
                {"id": c.content_id, "quantity": c.quantity, "item_price": float(c.item_price)}
                for c in payload.contents
            ]
        if payload.order_number:
            custom["order_id"] = payload.order_number
        if custom:
            event["custom_data"] = custom

        body: dict = {"data": [event]}
        if self.test_event_code:
            body["test_event_code"] = self.test_event_code
        return body
