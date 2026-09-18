"""Flush the storefront's cached tracking configuration when the Marketing screen changes.

`storefront/src/lib/marketing.ts` fetches `/marketing/config/` once per render pass and
caches it under the `marketing` tag. That fetch decides three things a stale answer gets
WRONG rather than merely late:

  * `tracking_enabled` — the master switch. Its whole reason to exist is that "a pixel is
    doing something we did not intend" should be answerable with one checkbox and not a
    deploy (see `MarketingSettings`). A switch that takes five minutes to bite is not that.
  * `consent_required_countries` — a legal position about whose consent must be collected
    before anything is stored. Widening it and then serving the old list for five minutes
    means five minutes of not asking people the law says to ask.
  * the channel list and its pixel ids — a corrected id is worthless while the browser is
    still being handed the wrong one.

Thin on purpose: the actual caller — a fire-and-forget daemon thread with a 3s timeout,
logged and swallowed on failure, a no-op until `REVALIDATE_SECRET` is set — lives in
`apps.cms.revalidate.notify_storefront` and is reused rather than copied. No coalescing
either: unlike the catalogue this is an operator saving one form, which is exactly the
case `apps/catalog/revalidate.py` says not to bother coalescing. What this module owns is
the NAME of the tag, which `storefront/src/lib/marketing.ts` must match.

── WHAT IS DELIBERATELY NOT WIRED ──────────────────────────────────────────────────────

`OrderAttribution` and `ConversionEvent`. Both are in this app and neither appears in
`PublicMarketingConfigSerializer`, so neither is in the cached payload — and
`ConversionEvent` in particular is written on every order, which would mean flushing the
tracking config once per sale to publish a value that had not changed.
"""

from apps.cms.revalidate import notify_storefront

STOREFRONT_TAG = "marketing"


def notify_marketing_changed(*_args, **_kwargs) -> None:
    """Signal receiver for `MarketingChannel`: any write flushes the one tag.

    No `created` skip here, unlike the settings singleton below. A channel row genuinely
    can be born meaningful — somebody adding one in the Django admin with a pixel id
    already in it — and skipping that would leave the browser loading nothing for a TTL.
    The create that happens in bulk, `ensure_channel_rows()`, never reaches this: it uses
    `bulk_create`, which sends no signals at all.
    """
    notify_storefront([STOREFRONT_TAG])


def notify_marketing_settings_changed(*_args, created: bool = False, **_kwargs) -> None:
    """Signal receiver for the `MarketingSettings` singleton.

    CREATION IS SKIPPED for the same reason `apps.core.revalidate` skips it on
    `BusinessDecisions`, and the mechanism is identical: `MarketingSettings.load()` is a
    `get_or_create(pk=1)`, and it is called by the PUBLIC config view on every request
    (`MarketingConfigView.get_object`). Materialising the defaults publishes nothing that
    anybody was being shown differently a moment earlier, so there is nothing to flush —
    and firing on create would mean the first storefront read of a fresh database POSTs
    back at the storefront that made it, plus a real POST out of every test that happens
    to touch the endpoint with a secret configured.
    """
    if created:
        return
    notify_storefront([STOREFRONT_TAG])
