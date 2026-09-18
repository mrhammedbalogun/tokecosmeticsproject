"""Flush the STOREFRONT's catalogue cache tags on catalogue writes.

Companion to `apps.catalog.signals`, which bumps Django's own cache version. That counter
only reaches responses this service renders; the storefront holds its own copy of the same
data under Next's `catalog` / `product:<slug>` tags, and nothing was flushing those. A
price edit therefore went live in the API immediately and on tokecosmetics.com up to
`CATALOG_REVALIDATE` seconds later.

The caller itself — a fire-and-forget daemon thread with a 3s timeout, logged and
swallowed on failure, a no-op until `REVALIDATE_SECRET` is set — lives in
`apps.cms.revalidate.notify_storefront` and is reused rather than copied. This module owns
two things: which TAGS a given write invalidates, and the COALESCING below.

── WHY COALESCING, WHEN cms/ AND stores/ DO NOT BOTHER ─────────────────────────────────

Those fire on an operator saving one banner or one shop. Catalogue writes arrive in
loops: `apps/migration_wp/importers/products.py` saves every product in turn, a price sync
walks every variant, and `bulk_create` aside, each save is its own signal. Notifying
per-save would start one thread per row — thousands on a re-import — to deliver the same
`catalog` tag over and over.

So tags accumulate on a per-transaction set and go out ONCE, on commit.

── AND WHY THERE ARE TWO DELIVERY PATHS, NOT ONE ───────────────────────────────────────

There is no transaction to coalesce into in autocommit mode, and `queue_tags` must not
pretend otherwise. `post_save` is sent OUTSIDE the atomic block Django uses for the write
(`django/db/models/base.py::save_base` — the `with context_manager` closes before
`post_save.send`), so a `.save()` that nobody wrapped has ALREADY COMMITTED by the time a
receiver runs. `transaction.on_commit` in that state does not defer anything; it invokes
the callback inline, immediately, before the caller can put a single tag in the set.

The first version of this module registered the hook before filling the set, and the
consequence was total: `_flush` ran against an empty set, returned, cleared the
thread-local, and the tags added on the next line were delivered to nobody — silently,
with no log line and no failed request. Production HTTP writes were unaffected only by
the accident that `prod.py` sets `ATOMIC_REQUESTS = True`; every Celery task, management
command, shell session and dev/staging request flushed nothing at all.

So the mode is decided FIRST, and the tags are in hand BEFORE anything is registered:

  in an atomic block  -> add to the pending set, register ONE `on_commit` flush
  in autocommit       -> the write is already durable; deliver now, inline
  manual transactions -> refuse (see `queue_tags`); there is no commit hook to use

── WHAT IS DELIBERATELY NOT WIRED ──────────────────────────────────────────────────────

STOCK. `in_stock` and `purchasable_variant_count` are in the cached payloads, but stock
lives in `apps.inventory.StockItem` and moves on every order line. Flushing the whole
catalogue per checkout would undo the caching this exists to protect, so stock drift stays
covered by the TTL — and the PDP re-checks stock at add-to-cart, which is the moment that
actually has to be right.
"""

from __future__ import annotations

import logging
import threading

from django.db import transaction

from apps.cms.revalidate import notify_storefront

log = logging.getLogger(__name__)

CATALOG_TAG = "catalog"

_pending = threading.local()


def _slug_of(instance: object) -> str | None:
    """The PRODUCT slug a write belongs to, or None when the write names no product.

    Resolved by type, never by duck-typing a `slug` attribute: Category, Brand and
    Collection all carry one, and walking to it produced `product:face` for a category
    rename — a tag no fetch is filed under, so a real product page would have gone on
    serving stale data while the payload looked plausible.

    Deliberately forgiving beyond that. On a cascade delete the parent row may already be
    gone, and a missing slug must cost the narrow tag only — the broad `catalog` tag still
    goes out, so the page still refreshes.
    """
    from apps.catalog.models import Product  # local: signals import this module

    try:
        if isinstance(instance, Product):
            return instance.slug or None
        for path in ("product.slug", "variant.product.slug"):
            target: object | None = instance
            for part in path.split("."):
                target = getattr(target, part, None)
                if target is None:
                    break
            if isinstance(target, str) and target:
                return target
    except Exception:  # noqa: BLE001 — a cache tag is never worth raising for
        log.debug("could not resolve a product slug for revalidation", exc_info=True)
    return None


def _callback_still_registered(conn) -> bool:
    """Is our on_commit hook still queued on this connection?

    Django DROPS pending on_commit callbacks when a transaction rolls back, and gives no
    rollback hook to notice. Without this check the pending set outlived its callback: the
    next `queue_tags` found a non-None set, skipped registering a new hook, and
    revalidation went silently dead for the life of that worker thread. Found by running
    these tests inside the full suite, where `pytest.mark.django_db` rolls back every test.
    """
    return any(entry[1] is _flush for entry in conn.run_on_commit)


def queue_tags(tags: list[str]) -> None:
    """Collect tags for this write; deliver them once, deduplicated, after it commits.

    Inside an atomic block that means on commit. In autocommit it means now — the row is
    already durable, and there is no later moment to wait for. See the module docstring
    for what registering the hook before filling the set used to cost.
    """
    if not tags:
        return
    conn = transaction.get_connection()

    if not conn.in_atomic_block:
        if not conn.get_autocommit():
            # Manual transaction management (`set_autocommit(False)`): the write is NOT
            # committed, and Django refuses `on_commit` here — it raises
            # TransactionManagementError. Delivering anyway would advertise a row that a
            # rollback could still take back, which is the one thing this must never do.
            # Nothing in this codebase manages transactions by hand; if something starts
            # to, this line is how it finds out, and the TTL covers the gap meanwhile.
            log.warning(
                "storefront revalidation skipped for %s: no commit hook is available "
                "under manual transaction management", sorted(set(tags)),
            )
            return
        # AUTOCOMMIT. `save()` has already committed (post_save is sent after the write's
        # context manager closes), so this is a post-commit delivery, not an early one.
        # No coalescing is possible or wanted: each save is its own transaction, and
        # holding tags back would mean holding them for a commit that already happened.
        _deliver(sorted(set(tags)))
        return

    # A FRESH SET AND A FRESH HOOK ARE ONE DECISION, not two. Every pending set needs
    # exactly one `_flush` registered against it, and `_flush` clears the set when it
    # runs — so "we just made a set" is precisely "we owe it a hook". Deriving the two
    # from separate conditions looks equivalent and is not: `_callback_still_registered`
    # can report True for a hook that has already fired (Django clears `run_on_commit`
    # on commit, but `captureOnCommitCallbacks` does not), which would leave a brand-new
    # set with nothing registered to deliver it. A product DELETE reaches exactly that
    # state, and it is how this line got its test.
    pending: set[str] | None = getattr(_pending, "tags", None)
    starting_a_new_batch = pending is None or not _callback_still_registered(conn)
    if starting_a_new_batch:
        pending = set()
        _pending.tags = pending
    # TAGS FIRST, HOOK SECOND — always, even though inside an atomic block `on_commit`
    # genuinely defers. Keeping the order identical in both branches means the invariant
    # "a registered flush always has its tags" does not depend on which mode we are in.
    pending.update(tags)
    if starting_a_new_batch:
        transaction.on_commit(_flush)


def _deliver(tags: list[str]) -> None:
    """Hand a finished, sorted tag list to the notifier, swallowing anything it raises.

    Every caller reaches this AFTER the write is durable — `on_commit` by definition, and
    autocommit because the row was committed before the signal fired. So raising could
    only turn a saved product into a 500 for an operator whose save actually worked. The
    TTL is the fallback, as ever.
    """
    if not tags:
        return
    try:
        notify_storefront(tags)
    except Exception:  # noqa: BLE001
        log.warning("could not queue a storefront revalidation for %s", tags, exc_info=True)


def _flush() -> None:
    tags = getattr(_pending, "tags", None)
    _pending.tags = None
    if not tags:
        return
    # Sorted so the payload is stable and a test can assert it without ordering games.
    _deliver(sorted(tags))


def tags_for(instance: object) -> list[str]:
    """`catalog`, plus the product-specific tag when the write names a product.

    BOTH, not one or the other: the storefront tags a product detail fetch
    `["catalog", "product:<slug>"]` and every listing fetch `["catalog"]`, so a price or
    image change has to reach the grid as well as the page.
    """
    slug = _slug_of(instance)
    return [CATALOG_TAG, f"product:{slug}"] if slug else [CATALOG_TAG]


def notify_catalog_changed(instance: object) -> None:
    """Entry point for `apps.catalog.signals` — one call per watched write."""
    queue_tags(tags_for(instance))
