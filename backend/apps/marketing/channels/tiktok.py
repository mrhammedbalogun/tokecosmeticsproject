"""TikTok Events API 2.0.

    POST https://business-api.tiktok.com/open_api/v1.3/event/track/
    header: Access-Token

Verified 2026-08-29.

── THE VERSION TRAP ────────────────────────────────────────────────────────────────────

Most examples on the internet — including several still-current integration guides —
show the OLD shape:

    {"pixel_code": ..., "event": ..., "context": {"user": {...}, "ip": ...},
     "timestamp": "2020-09-17T19:49:27Z"}

That is Events API 1.0/1.2. It is not what this file builds and it is not what the v1.3
endpoint wants. 2.0 is `event_source` + `event_source_id` + `data[]`, with `user`,
`page` and `properties` INSIDE each data element, and `event_time` as Unix seconds.
Anyone reading a blog post while debugging this file will be reading about a different
API; the shape below came from the vendor.

── FIELD RULES ─────────────────────────────────────────────────────────────────────────

- Hashed (SHA-256): `email`, `phone` (E.164 first), `external_id`.
- Raw: `ttclid`, `ttp`, `ip`, `user_agent`.
- `page.url` is REQUIRED for web events and must start with http/https. An event without
  one is rejected, so `events.py` always supplies a source URL for TikTok.
- TikTok answers **HTTP 200 with `code != 0`** for business-level refusals. The default
  "2xx means accepted" reading would record those as sent, which is why `interpret` is
  overridden below — this is the exact bug that makes an integration look healthy while
  the ad account receives nothing.
"""
from __future__ import annotations

import httpx

from apps.marketing import hashing
from apps.marketing.channels.base import ChannelResult, ConversionChannel
from apps.marketing.payloads import (
    ADD_TO_CART, INITIATE_CHECKOUT, PAGE_VIEW, PURCHASE, VIEW_CONTENT, ConversionPayload,
)

ENDPOINT = "https://business-api.tiktok.com/open_api/v1.3/event/track/"

# `CompletePayment`, not `PlaceAnOrder`. Both are standard TikTok events and they mean
# different things: PlaceAnOrder is an order submitted, CompletePayment is money taken.
# Ours fires from the paid transition, so it is the second one — and sending the wrong
# one teaches TikTok to optimise for a step the shop does not get paid at.
EVENT_NAMES = {
    PAGE_VIEW: "Pageview",
    VIEW_CONTENT: "ViewContent",
    ADD_TO_CART: "AddToCart",
    INITIATE_CHECKOUT: "InitiateCheckout",
    PURCHASE: "CompletePayment",
}


class TikTokChannel(ConversionChannel):
    code = "tiktok"

    def endpoint(self) -> str:
        return ENDPOINT

    def headers(self) -> dict:
        return {"Content-Type": "application/json", "Access-Token": self.access_token}

    def build(self, payload: ConversionPayload) -> dict:
        user = payload.user
        cookies = user.pixel_cookies or {}
        clicks = user.click_ids or {}

        user_block: dict = {}

        def _add(key: str, value: str) -> None:
            if value:
                user_block[key] = value

        _add("email", hashing.hashed_email(user.email))
        _add("phone", hashing.hashed_phone(user.phone))
        _add("external_id", hashing.sha256_hex(user.external_id))
        # Raw — TikTok's click id and its own first-party cookie.
        _add("ttclid", clicks.get("ttclid", ""))
        _add("ttp", cookies.get("ttp", ""))
        _add("ip", user.client_ip)
        _add("user_agent", user.client_user_agent)

        event: dict = {
            "event": EVENT_NAMES[payload.event_name],
            "event_time": payload.event_time,
            "event_id": payload.event_id,
            "user": user_block,
        }
        if payload.source_url:
            event["page"] = {"url": payload.source_url}

        properties: dict = {}
        if payload.currency:
            properties["currency"] = payload.currency
            properties["value"] = float(payload.value)
        if payload.contents:
            properties["content_type"] = "product"
            properties["contents"] = [
                {
                    "content_id": c.content_id,
                    "content_type": "product",
                    "content_name": c.name,
                    "quantity": c.quantity,
                    "price": float(c.item_price),
                }
                for c in payload.contents
            ]
        if payload.order_number:
            properties["order_id"] = payload.order_number
        if properties:
            event["properties"] = properties

        body: dict = {
            "event_source": "web",
            "event_source_id": self.pixel_id,
            "data": [event],
        }
        if self.test_event_code:
            body["test_event_code"] = self.test_event_code
        return body

    def interpret(self, response: httpx.Response) -> ChannelResult:
        """TikTok's envelope: `{"code": 0, "message": "OK", ...}` on success, and a
        NON-ZERO code inside an HTTP 200 for a business refusal (bad pixel id, malformed
        user block, expired token). Judging on the HTTP status alone would mark every one
        of those "sent"."""
        result = super().interpret(response)
        if not result.ok:
            return result
        try:
            envelope = response.json()
        except ValueError:
            # A 200 that is not JSON is not TikTok answering — an interstitial or a
            # proxy. Retryable: the real endpoint may well be reachable next time.
            return ChannelResult(ok=False, status=response.status_code,
                                 excerpt=result.excerpt, retryable=True)
        if envelope.get("code") == 0:
            return result
        # 40100/40001-class codes are our body being wrong and will not improve; the
        # 5xxxx range is theirs. Anything unrecognised is treated as permanent, so a
        # broken payload cannot loop for ever.
        code = envelope.get("code")
        retryable = isinstance(code, int) and code >= 50000
        return ChannelResult(
            ok=False, status=response.status_code,
            excerpt=f"code={code} message={envelope.get('message', '')}"[:1000],
            retryable=retryable,
        )
