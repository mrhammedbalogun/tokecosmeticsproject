"""Flush the storefront's combo cache tags on combo writes.

Thin, like `apps.stores.revalidate`: the caller and the per-transaction coalescing both
live elsewhere (`apps.cms.revalidate.notify_storefront`, `apps.catalog.revalidate.queue_tags`).
What this module owns is the tag set, which `storefront/src/lib/combos.ts` must match.

THREE TAGS, not one. That file tags the index `["catalog", "combos"]` and a detail page
`["catalog", "combos", "combo:<slug>"]` — so a combo edit has to reach its own page, the
Combo Deals listing, AND the homepage row, which is a plain catalogue fetch.
"""

from __future__ import annotations

from apps.catalog.revalidate import CATALOG_TAG, queue_tags

COMBOS_TAG = "combos"


def _slug_of(instance: object) -> str | None:
    """A combo's slug, whether the write was the combo or one of its rows."""
    for path in ("slug", "combo.slug"):
        target: object | None = instance
        for part in path.split("."):
            target = getattr(target, part, None)
            if target is None:
                break
        if isinstance(target, str) and target:
            return target
    return None


def notify_combo_changed(instance: object) -> None:
    slug = _slug_of(instance)
    tags = [CATALOG_TAG, COMBOS_TAG]
    if slug:
        tags.append(f"combo:{slug}")
    queue_tags(tags)
