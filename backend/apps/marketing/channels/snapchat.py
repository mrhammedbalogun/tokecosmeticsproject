"""Snapchat Conversions API v3.

    POST https://tr.snapchat.com/v3/{pixel_id}/events?access_token=...

Verified 2026-08-29.

── v2 IS GONE ──────────────────────────────────────────────────────────────────────────

Snap deprecated Conversions API v2 in early 2025. A v2 example (flat body, `pixel_id` in
the payload, `hashed_email`) will not work and is what most third-party write-ups still
show. v3 is `{"data": [...]}` with `user_data` / `custom_data` per event.

── SNAP'S OWN SPELLINGS ────────────────────────────────────────────────────────────────

Snapchat disagrees with the other three about nearly every surface detail, and each
disagreement is a silent failure rather than an error:

- Event names are **UPPER_SNAKE**: `PURCHASE`, `ADD_CART`, `VIEW_CONTENT`,
  `START_CHECKOUT`, `PAGE_VIEW`. Note `ADD_CART`, not `ADD_TO_CART`.
- `action_source` is `"WEB"`, upper case.
- `custom_data.value` is a **STRING**. Meta wants a number for the same field.
- `em` / `ph` are SHA-256 hashed **arrays**, like Meta's.
- The click id is `sc_click_id`, taken from the `&ScCid=` URL parameter, and the pixel
  cookie is `sc_cookie1` (`_scid`). Both raw.

Matching needs at least one of: hashed email, hashed phone, or ip + user agent.
"""
from __future__ import annotations

from apps.marketing import hashing
from apps.marketing.channels.base import ConversionChannel
from apps.marketing.payloads import (
    ADD_TO_CART, INITIATE_CHECKOUT, PAGE_VIEW, PURCHASE, VIEW_CONTENT, ConversionPayload,
)

EVENT_NAMES = {
    PAGE_VIEW: "PAGE_VIEW",
    VIEW_CONTENT: "VIEW_CONTENT",
    ADD_TO_CART: "ADD_CART",
    INITIATE_CHECKOUT: "START_CHECKOUT",
    PURCHASE: "PURCHASE",
}


class SnapchatChannel(ConversionChannel):
    code = "snapchat"

    def endpoint(self) -> str:
        return f"https://tr.snapchat.com/v3/{self.pixel_id}/events?access_token={self.access_token}"

    def build(self, payload: ConversionPayload) -> dict:
        user = payload.user
        cookies = user.pixel_cookies or {}
        clicks = user.click_ids or {}

        user_data: dict = {}

        def _add(key: str, value: str, *, as_list: bool = False) -> None:
            if value:
                user_data[key] = [value] if as_list else value

        _add("em", hashing.hashed_email(user.email), as_list=True)
        _add("ph", hashing.hashed_phone(user.phone), as_list=True)
        _add("client_ip_address", user.client_ip)
        _add("client_user_agent", user.client_user_agent)
        _add("sc_click_id", clicks.get("sccid", ""))
        _add("sc_cookie1", cookies.get("scid", ""))
        _add("external_id", hashing.sha256_hex(user.external_id))

        event: dict = {
            "event_name": EVENT_NAMES[payload.event_name],
            "event_time": payload.event_time,
            "event_id": payload.event_id,
            "action_source": "WEB",
            "user_data": user_data,
        }
        if payload.source_url:
            event["event_source_url"] = payload.source_url

        custom: dict = {}
        if payload.currency:
            custom["currency"] = payload.currency
            # A STRING. Snap's schema types this as a string and a JSON number is a
            # 400 — the one place a copy-paste from meta.py would break.
            custom["value"] = f"{payload.value}"
        if payload.contents:
            custom["contents"] = [
                {
                    "id": c.content_id,
                    "quantity": c.quantity,
                    "item_price": f"{c.item_price}",
                    **({"brand": c.brand} if c.brand else {}),
                }
                for c in payload.contents
            ]
        if payload.order_number:
            custom["order_id"] = payload.order_number
        if custom:
            event["custom_data"] = custom

        return {"data": [event]}
