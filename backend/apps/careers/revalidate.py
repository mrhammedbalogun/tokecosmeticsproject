"""Flush the storefront's careers cache on every posting write.

Thin on purpose: the actual caller — a fire-and-forget daemon thread with a 3s timeout,
logged and swallowed on failure, a no-op until `REVALIDATE_SECRET` is set — lives in
`apps.cms.revalidate.notify_storefront` and is reused rather than copied. The only thing
this app owns is the NAME of its tag, which `storefront/src/lib/careers.ts` must match.

WHY LOCATIONS FIRE IT TOO. A posting's cities are what the board's filter is built from
and what the apply form's picker offers. Adding Enugu without flushing leaves a role
advertised in a city its own form refuses to accept, which reads as a broken form rather
than as a stale cache.
"""

from apps.cms.revalidate import notify_storefront

STOREFRONT_TAG = "careers"


def notify_careers_changed(*_args, **_kwargs) -> None:
    notify_storefront([STOREFRONT_TAG])
