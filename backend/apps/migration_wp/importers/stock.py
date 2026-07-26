"""Stock import phase (Plan-21 Task 11).

Seeds a placeholder on-hand quantity per variant at the Lagos warehouse from
WooCommerce's `_stock_status` meta -- WooCommerce here tracks quantities on
only 21 of 69 products, so a real count is not available from the source and
real counts are entered by hand before launch.

The UK warehouse is deliberately NOT seeded here: the international store has
no SKUs to match on and no stock quantities in the source data at all.

THE CLOBBER GUARD. Hammed's team will enter real Lagos and UK stock counts by
hand before launch. The Plan-27 cutover then runs a fresh full migration
against current live data. Without protection, that run would reset every
hand-entered count back to the placeholder -- the single most destructive
thing this migration could do. So the guard is automatic (not opt-in):
`import_stock` refuses to touch any StockItem whose most recent
StockMovement.reason is not "migration" (i.e. anything a human, or any
process other than this importer, has touched since). `force` overrides it;
`--skip-stock` at the command layer skips the phase wholesale, for runs after
manual counts already exist.
"""
from __future__ import annotations

from apps.catalog.models import ProductVariant
from apps.inventory.models import StockItem, StockMovement, Warehouse

from .common import logger

PLACEHOLDER_STOCK = 100
LAGOS = "Lagos HQ"


def _is_hand_edited(item: StockItem) -> bool:
    """True when the latest movement on this item was not written by this
    importer -- i.e. a human (or any other process) has touched it since.

    An item with NO movement rows at all was created outside this importer
    (there is no code path in `import_stock` that creates a StockItem without
    also writing a "migration" StockMovement in the same call). That's exactly
    the kind of out-of-band state the guard exists to protect, so the absence
    of a "migration" movement is treated the same as a non-migration reason:
    hand-edited, protect it.
    """
    latest = item.movements.order_by("-created_at", "-id").first()
    if latest is None:
        return True
    return latest.reason != "migration"


def import_stock(data, force, stdout=None) -> tuple[int, int]:
    """Seed a placeholder StockItem per variant at Lagos HQ from `_stock_status`.

    Returns (seeded, protected).
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
    for row in data["products"]:
        wp_id = row["ID"]
        meta = meta_all.get(str(wp_id), {})
        quantity = PLACEHOLDER_STOCK if meta.get("_stock_status") == "instock" else 0

        for variant in variants_by_product_wp_id.get(wp_id, []):
            item = StockItem.objects.filter(variant=variant, warehouse=lagos).first()

            if item is not None and _is_hand_edited(item) and not force:
                protected += 1
                message = (
                    f"protected: stock item for {variant.sku} at {lagos.name} has been "
                    f"hand-edited (quantity={item.quantity}) -- migration left it alone"
                )
                logger.warning(message)
                if stdout is not None:
                    stdout.write(message)
                continue

            if item is None:
                item = StockItem(variant=variant, warehouse=lagos, quantity=quantity)
            else:
                item.quantity = quantity
            item.save()

            StockMovement.objects.create(
                stock_item=item,
                delta_quantity=quantity,
                reason="migration",
                note=f"seeded from WooCommerce _stock_status={meta.get('_stock_status')!r}",
            )
            seeded += 1

    return seeded, protected
