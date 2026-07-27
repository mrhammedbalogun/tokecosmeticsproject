"""Stock import phase (Plan-21 Task 11).

Seeds a placeholder on-hand quantity per variant at the Lagos warehouse from
WooCommerce's `_stock_status` meta -- WooCommerce here tracks quantities on
only 21 of 69 products, so a real count is not available from the source and
real counts are entered by hand before launch.

The UK warehouse is deliberately NOT seeded here: the international store has
no SKUs to match on and no stock quantities in the source data at all.

Two assumptions worth stating plainly:

1. Variation stock status is inherited from the parent product. The catalog
   extraction step also captures `_stock_status` on variations, but this
   importer reads only the parent product's and applies it to every one of
   that product's variants. That is correct for this store today (quantities
   are tracked on only 21 of 69 products, at the product level), but it is an
   assumption, not a fact -- Task 15's dry run against live data should check
   for variation-level `_stock_status` values that disagree with their
   parent's.
2. Draft products get stock seeded too. Uniform behaviour (no status
   special-case) is intentional, but it means a draft product can carry a
   placeholder 100 that nobody has verified. The real-count worklist in
   Task 13 is what catches this before launch, not this importer.

THE CLOBBER GUARD. Hammed's team will enter real Lagos and UK stock counts by
hand before launch. The Plan-27 cutover then runs a fresh full migration
against current live data. Without protection, that run would reset every
hand-entered count back to the placeholder -- the single most destructive
thing this migration could do. So the guard is automatic (not opt-in):
`import_stock` refuses to touch any StockItem whose most recent
StockMovement.reason is not "migration" (i.e. anything a human, or any
process other than an ordinary run of this importer, has touched since).
`force` overrides it for one run, but a forced overwrite is recorded with
reason="adjustment" (not "migration") precisely so the guard re-arms itself
on the very next run -- otherwise the escape hatch, used once, would leave
that SKU permanently unprotected. `--skip-stock` at the command layer skips
the phase wholesale, for runs after manual counts already exist.
"""
from __future__ import annotations

from apps.catalog.models import ProductVariant
from apps.inventory.models import StockItem, StockMovement, Warehouse

from .common import logger

PLACEHOLDER_STOCK = 100
LAGOS = "Lagos HQ"


def _is_hand_edited(item: StockItem) -> bool:
    """True when the latest movement on this item was not written as an
    ordinary migration seed -- i.e. a human, or a forced --force-stock run,
    has touched it since.

    An item with NO movement rows at all was created outside this importer
    (there is no code path in `import_stock` that creates a StockItem without
    also writing a movement in the same call). That's exactly the kind of
    out-of-band state the guard exists to protect, so the absence of a
    "migration" movement is treated the same as a non-migration reason:
    hand-edited, protect it.
    """
    latest = item.movements.order_by("-created_at", "-id").first()
    if latest is None:
        return True
    return latest.reason != "migration"


def import_stock(data, force) -> tuple[int, int, list[str]]:
    """Seed a placeholder StockItem per variant at Lagos HQ from `_stock_status`.

    Returns (seeded, protected, protected_messages). protected_messages is a
    list of human-readable strings, one per skipped item; the caller (the
    import_catalog command, which owns stdout) decides how to display them.
    This function only logs them via `logger.warning`.
    """
    lagos, _ = Warehouse.objects.get_or_create(
        name=LAGOS, defaults={"location_country": "NG"}
    )

    meta_all = data["meta"]
    variants_by_product_wp_id: dict[int, list[ProductVariant]] = {}
    for v in ProductVariant.objects.select_related("product"):
        variants_by_product_wp_id.setdefault(v.product.legacy_wp_id, []).append(v)

    seeded = 0
    protected = 0
    protected_messages: list[str] = []
    for row in data["products"]:
        wp_id = row["ID"]
        meta = meta_all.get(str(wp_id), {})
        quantity = PLACEHOLDER_STOCK if meta.get("_stock_status") == "instock" else 0

        for variant in variants_by_product_wp_id.get(wp_id, []):
            item = StockItem.objects.filter(variant=variant, warehouse=lagos).first()
            hand_edited = item is not None and _is_hand_edited(item)

            if hand_edited and not force:
                protected += 1
                message = (
                    f"protected: stock item for {variant.sku} at {lagos.name} has been "
                    f"hand-edited (quantity={item.quantity}) -- migration left it alone"
                )
                logger.warning(message)
                protected_messages.append(message)
                continue

            # delta_quantity is a DELTA, not the new absolute value -- the
            # ledger (StockMovement) is the source of truth reconcile() sums
            # against, so writing the absolute quantity here corrupts it on
            # every re-touch of an existing item.
            previous = item.quantity if item is not None else 0
            delta = quantity - previous

            if hand_edited and force:
                # A forced overwrite must NOT be recorded as reason="migration" --
                # doing so would make the guard treat this item as an ordinary,
                # untouched migration seed on the very next run, silently
                # clobbering the hand-entered count all over again. Recording
                # it as "adjustment" re-arms the guard immediately: the next
                # ordinary run sees a non-migration latest movement and
                # protects the item, as it should.
                logger.warning(
                    "FORCED OVERWRITE: stock item for %s at %s was hand-edited "
                    "(quantity=%s) -- --force-stock discarded it and reset to %s",
                    variant.sku, lagos.name, previous, quantity,
                )
                reason = "adjustment"
                note = (
                    f"Plan-21 forced overwrite of a hand-edited count "
                    f"(--force-stock); discarded quantity={previous}"
                )
            else:
                reason = "migration"
                note = f"seeded from WooCommerce _stock_status={meta.get('_stock_status')!r}"

            if item is None:
                item = StockItem(variant=variant, warehouse=lagos, quantity=quantity)
            else:
                item.quantity = quantity
            item.save()

            StockMovement.objects.create(
                stock_item=item, delta_quantity=delta, reason=reason, note=note,
            )
            seeded += 1

    return seeded, protected, protected_messages
