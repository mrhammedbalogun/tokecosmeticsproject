"""Which adapter serves which channel, and how one is built from a configuration row.

A registry rather than an if-chain for the reason `payments.gateways.registry` is one:
the admin screen needs to list what the platform CAN do independently of what any row
says it does, and a hardcoded list in the UI is how that drifts.
"""
from __future__ import annotations

from apps.marketing.channels.base import ConversionChannel
from apps.marketing.channels.ga4 import Ga4Channel, debug_enabled
from apps.marketing.channels.google_ads import GoogleAdsChannel
from apps.marketing.channels.meta import MetaChannel
from apps.marketing.channels.snapchat import SnapchatChannel
from apps.marketing.channels.tiktok import TikTokChannel
from apps.marketing.credentials import credential_for

_REGISTRY: dict[str, type[ConversionChannel]] = {
    MetaChannel.code: MetaChannel,
    TikTokChannel.code: TikTokChannel,
    SnapchatChannel.code: SnapchatChannel,
    Ga4Channel.code: Ga4Channel,
    GoogleAdsChannel.code: GoogleAdsChannel,
}


def server_side_channels() -> list[str]:
    return sorted(_REGISTRY)


def build_channel(row) -> ConversionChannel | None:
    """An adapter for a `MarketingChannel` row, or None when the platform has no
    server-side sender. Raises nothing: an unconfigured channel is filtered out in
    `events.py` long before this is called."""
    cls = _REGISTRY.get(row.code)
    if cls is None:
        return None
    kwargs = {
        "pixel_id": row.pixel_id,
        "access_token": credential_for(row.code),
        "test_event_code": row.test_event_code,
    }
    if cls is Ga4Channel:
        kwargs["debug"] = debug_enabled()
    if cls is GoogleAdsChannel:
        # Google alone is addressed by a second pair of ids — which advertiser account,
        # and which conversion action inside it. See channels/google_ads.py.
        kwargs["account_id"] = row.server_account_id
        kwargs["destination_id"] = row.server_destination_id
    return cls(**kwargs)
