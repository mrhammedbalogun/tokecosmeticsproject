"""Flush the storefront's cached referral terms whenever `BusinessDecisions` changes.

WHY THIS IS NOT OPTIONAL. `/affiliates` fetches `/referrals/terms/` with
`next: { revalidate: 3600, tags: ["referral-terms"] }` — an hour. Without this, an Owner
who drops the commission to 8% would leave the public page advertising 10% for up to an
hour, while the checkout already paid 8%. The whole reason those numbers are served from
the API rather than written into JSX is that the advertisement and the payment must move
together; an hour-long cache is that same drift with a timer on it.

Thin on purpose: the actual caller — a fire-and-forget daemon thread with a 3s timeout,
logged and swallowed on failure, a no-op until `REVALIDATE_SECRET` is set — lives in
`apps.cms.revalidate.notify_storefront` and is reused rather than copied. The only thing
this module owns is the NAME of the tag, which `storefront/src/lib/referral-terms.ts`
must match.
"""

from apps.cms.revalidate import notify_storefront

STOREFRONT_TAG = "referral-terms"


def notify_decisions_changed(*_args, created: bool = False, **_kwargs) -> None:
    """Signal receiver: a CHANGE to the singleton invalidates the one terms tag.

    CREATION IS SKIPPED, and not as an optimisation. `BusinessDecisions.load()` creates
    the row from the settings defaults on first touch, and those defaults are exactly what
    the storefront already believes — its `PUBLISHED_TERMS` fallback is pinned to the same
    values by a test. Materialising them changes nothing anybody is looking at, so there
    is nothing to flush.

    It also matters practically. `load()` is called on every commission accrual and every
    referred quote, and a test database rolls back between tests — so firing on create
    meant a real HTTP POST to the storefront from inside hundreds of unrelated tests
    wherever `REVALIDATE_SECRET` happens to be set, which on a developer machine it is.
    Skipping the create leaves exactly the firings that mean something: an Owner or
    Manager saving a new number.
    """
    if created:
        return
    notify_storefront([STOREFRONT_TAG])
