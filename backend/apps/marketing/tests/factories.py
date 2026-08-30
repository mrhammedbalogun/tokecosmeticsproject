"""Helpers for the marketing suite.

Builds real `Order` rows through the ORM, borrowing the referral suite's `make_order`
for the same reason it exists there: every assertion about a conversion event's `value`
is an assertion about the order's own money columns, so a test has to be able to set
them precisely and watch the number follow.
"""
from __future__ import annotations

from apps.marketing.models import MarketingChannel, MarketingSettings, OrderAttribution
from apps.orders.models import OrderItem
from apps.referrals.tests.factories import customer, gb, make_order, ng  # noqa: F401

CONFIGURED = {
    "meta": "META_CAPI_ACCESS_TOKEN",
    "tiktok": "TIKTOK_EVENTS_ACCESS_TOKEN",
    "snapchat": "SNAPCHAT_CAPI_ACCESS_TOKEN",
    "ga4": "GA4_API_SECRET",
}


def configure(settings, *codes: str, token: str = "tok-123") -> None:
    """Put a credential in the environment for each named channel."""
    for code in codes:
        setattr(settings, CONFIGURED[code], token)


def channel(code: str = "meta", **kwargs) -> MarketingChannel:
    kwargs.setdefault("is_enabled", True)
    kwargs.setdefault("pixel_id", "PIXEL123")
    return MarketingChannel.objects.create(code=code, **kwargs)


def enable_tracking(**kwargs) -> MarketingSettings:
    row = MarketingSettings.load()
    for key, value in {"tracking_enabled": True, **kwargs}.items():
        setattr(row, key, value)
    row.save()
    return row


def attribution(order, *, marketing: bool = True, **kwargs) -> OrderAttribution:
    defaults = {
        "consent_marketing": marketing,
        "consent_analytics": True,
        "consent_version": 1,
        "click_ids": {"fbclid": "CLICK123", "ttclid": "TT123", "sccid": "SC123", "ts": 1700000000},
        "pixel_cookies": {"fbp": "fb.1.1700000000.999", "ttp": "ttp-abc", "scid": "scid-abc"},
        "client_ip": "102.89.1.1",
        "client_user_agent": "Mozilla/5.0 (test)",
        "event_source_url": "https://tokecosmetics.com/checkout",
    }
    defaults.update(kwargs)
    return OrderAttribution.objects.create(order=order, **defaults)


def add_item(order, *, sku="SKU-1", quantity=2, unit_price="2500.00", name="Radiance Serum"):
    return OrderItem.objects.create(
        order=order, product_name=name, sku=sku, quantity=quantity,
        unit_price=unit_price, line_total=str(int(quantity) * float(unit_price)),
    )
