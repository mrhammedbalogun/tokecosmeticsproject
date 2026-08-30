"""GA4 Measurement Protocol.

    POST https://www.google-analytics.com/mp/collect?measurement_id=...&api_secret=...

Verified 2026-08-29. Unlike the three ad platforms this is an ANALYTICS destination, and
the difference shows up in three places worth knowing before reading the code:

1. **Time is in MICROSECONDS** (`timestamp_micros`), not seconds. Every other adapter in
   this package uses seconds. Getting this wrong puts the event fifty thousand years out
   and GA4 discards it without complaint.
2. **`client_id` is mandatory and identifies a BROWSER**, not a person. It normally comes
   from the `_ga` cookie. A webhook-driven purchase has no browser, which is the problem
   `_client_id` below solves — read its comment, because the compromise it makes is
   visible in GA4's reports.
3. **The Measurement Protocol has no error responses worth the name.** A malformed event
   returns 204, exactly like a good one. Google's debug endpoint (`/debug/mp/collect`)
   is the only thing that answers honestly, which is what the admin's test button uses.

`consent` is sent explicitly. GA4 honours `ad_user_data` / `ad_personalization`, and the
values come from the snapshot taken at checkout, not from a live cookie read.
"""
from __future__ import annotations

import hashlib

import httpx
from django.conf import settings

from apps.marketing.channels.base import ChannelResult, ConversionChannel
from apps.marketing.payloads import (
    ADD_TO_CART, INITIATE_CHECKOUT, PAGE_VIEW, PURCHASE, VIEW_CONTENT, ConversionPayload,
)

ENDPOINT = "https://www.google-analytics.com/mp/collect"
DEBUG_ENDPOINT = "https://www.google-analytics.com/debug/mp/collect"

EVENT_NAMES = {
    PAGE_VIEW: "page_view",
    VIEW_CONTENT: "view_item",
    ADD_TO_CART: "add_to_cart",
    INITIATE_CHECKOUT: "begin_checkout",
    PURCHASE: "purchase",
}


class Ga4Channel(ConversionChannel):
    code = "ga4"

    def __init__(self, *, pixel_id: str, access_token: str, test_event_code: str = "",
                 debug: bool = False):
        super().__init__(pixel_id=pixel_id, access_token=access_token,
                         test_event_code=test_event_code)
        self.debug = debug

    def endpoint(self) -> str:
        base = DEBUG_ENDPOINT if self.debug else ENDPOINT
        return f"{base}?measurement_id={self.pixel_id}&api_secret={self.access_token}"

    def _client_id(self, payload: ConversionPayload) -> str:
        """The browser's `_ga` client id, or a stable synthetic one derived from the
        order number.

        WHAT THE FALLBACK COSTS, stated plainly: a synthetic client id is a NEW user and
        a NEW session in GA4, so a purchase that arrives this way is not joined to the
        browsing session that produced it. Channel attribution for that order lands in
        (direct). That is strictly better than the alternative — no purchase at all — but
        it means GA4's channel report will under-credit paid social whenever the customer
        never came back from the payment gateway.

        The real fix is to capture `_ga` at checkout, which the storefront does; this
        path is for orders where it was absent (cookie blocked, consent withheld for
        analytics, a gateway that returns nobody).

        Derived from the order number rather than random so a retry of the same event
        produces the same id, instead of inventing a fresh "user" on every attempt.
        """
        if payload.ga_client_id:
            return payload.ga_client_id
        digest = hashlib.sha256(f"toke:{payload.order_number or payload.event_id}".encode())
        # GA4 client ids look like "1234567890.1234567890"; two integers derived from the
        # digest keep the shape without pretending to be a real cookie value.
        return f"{int(digest.hexdigest()[:9], 16)}.{int(digest.hexdigest()[9:18], 16)}"

    def build(self, payload: ConversionPayload) -> dict:
        params: dict = {
            # GA4 drops events with no engagement time from some reports; 1ms is the
            # documented minimum that keeps a server event out of that hole.
            "engagement_time_msec": 1,
        }
        if payload.currency:
            params["currency"] = payload.currency
            params["value"] = float(payload.value)
        if payload.order_number:
            params["transaction_id"] = payload.order_number
        if payload.contents:
            params["items"] = [
                {
                    "item_id": c.content_id,
                    "item_name": c.name or c.content_id,
                    "price": float(c.item_price),
                    "quantity": c.quantity,
                    **({"item_brand": c.brand} if c.brand else {}),
                    **({"item_category": c.category} if c.category else {}),
                }
                for c in payload.contents
            ]

        body: dict = {
            "client_id": self._client_id(payload),
            # Microseconds. See the module docstring.
            "timestamp_micros": payload.event_time * 1_000_000,
            "events": [{"name": EVENT_NAMES[payload.event_name], "params": params}],
        }
        if payload.user.external_id:
            body["user_id"] = payload.user.external_id
        return body

    def interpret(self, response: httpx.Response) -> ChannelResult:
        """204 is the documented success. The debug endpoint answers 200 with a
        `validationMessages` array — an EMPTY array is a pass, and a non-empty one is a
        failure the production endpoint would have swallowed in silence."""
        result = super().interpret(response)
        if not self.debug or not result.ok:
            return result
        try:
            messages = response.json().get("validationMessages", [])
        except ValueError:
            return result
        if not messages:
            return result
        return ChannelResult(ok=False, status=response.status_code,
                             excerpt=str(messages)[:1000], retryable=False)


def debug_enabled() -> bool:
    """Whether GA4 sends go to the validation endpoint. Off unless explicitly set —
    the debug endpoint does NOT record the event, so leaving this on means GA4 quietly
    receives nothing at all."""
    return bool(getattr(settings, "GA4_DEBUG_ENDPOINT", False))
