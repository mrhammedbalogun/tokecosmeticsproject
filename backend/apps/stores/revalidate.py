"""Flush the storefront's store-locator cache on every `StoreLocation` write.

Thin on purpose: the actual caller — a fire-and-forget daemon thread with a 3s
timeout, logged and swallowed on failure, a no-op until `REVALIDATE_SECRET` is set —
lives in `apps.cms.revalidate.notify_storefront` and is reused rather than copied.
The storefront route it hits accepts any tag list, so the only thing this app owns
is the NAME of its tag, which `storefront/src/lib/stores.ts` must match.
"""

from apps.cms.revalidate import notify_storefront

STOREFRONT_TAG = "stores"


def notify_stores_changed(*_args, **_kwargs) -> None:
    """Signal receiver: any store write invalidates the one "stores" tag."""
    notify_storefront([STOREFRONT_TAG])
