"""Where each channel's server-side credential lives, and whether it is there.

Mirrors `apps.payments.checks.missing_settings_for` exactly, because it answers exactly
the same question about exactly the same kind of value: a secret that lets us write into
somebody's account, held in the environment, reported to the admin as present or absent
and never rendered back.

`google_ads` joined the table in Plan-44b. It was browser-only at first because
uploading conversions meant the Google Ads API — OAuth2 refresh token, developer token,
and an access application Google reviews for days. That path turned out to be CLOSED to
new adopters as of 2026-06-15, and its replacement, the Data Manager API, needs none of
it: one service account key and no application at all. See `channels/google_ads.py`.

`BROWSER_ONLY_CHANNELS` is kept, empty, on purpose. It is the seam every other module
already asks (`supports_server_side`), and a future channel with a browser tag and no
server API — there will be one — belongs in it rather than in a fresh special case.
"""
from __future__ import annotations

from django.conf import settings

# channel code -> the settings names its server-side sender needs.
CHANNEL_REQUIRED_SETTINGS: dict[str, list[str]] = {
    "meta": ["META_CAPI_ACCESS_TOKEN"],
    "tiktok": ["TIKTOK_EVENTS_ACCESS_TOKEN"],
    "snapchat": ["SNAPCHAT_CAPI_ACCESS_TOKEN"],
    "ga4": ["GA4_API_SECRET"],
    # Not a bearer token: the base64 of a Google service account JSON key. The variable
    # still behaves the same way for every reader here — present or absent.
    "google_ads": ["GOOGLE_ADS_DM_CREDENTIALS_B64"],
}

# Channels with a browser tag and no server API. Empty today; see the docstring.
BROWSER_ONLY_CHANNELS: frozenset[str] = frozenset()


def missing_settings_for(channel: str) -> list[str]:
    """Which required settings are blank. Empty list = ready to send."""
    return [
        name for name in CHANNEL_REQUIRED_SETTINGS.get(channel, [])
        if not getattr(settings, name, "")
    ]


def credential_for(channel: str) -> str:
    """The channel's server-side secret, or "" when it is not configured."""
    names = CHANNEL_REQUIRED_SETTINGS.get(channel, [])
    return getattr(settings, names[0], "") if names else ""


def supports_server_side(channel: str) -> bool:
    return channel not in BROWSER_ONLY_CHANNELS and channel in CHANNEL_REQUIRED_SETTINGS
