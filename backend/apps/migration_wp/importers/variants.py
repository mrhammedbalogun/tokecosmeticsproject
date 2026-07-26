"""Variant and price import phase.

Moved out of the `import_catalog` management command unchanged (Part A of the
Task 11 refactor) -- no behaviour change intended.
"""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

from apps.catalog.models import Product, ProductVariant
from apps.core.models import Currency
from apps.migration_wp.transform import generate_sku, parse_option_values
from apps.pricing.models import Price

from .common import LEGACY_SOURCE, logger


def import_variants_and_prices(data, skip_prices) -> tuple[int, int]:
    """WP variations (or the product itself, if simple) -> ProductVariant + Price.

    `sku` is the idempotency key for ProductVariant -- it has no legacy_wp_id.
    A variation's SKU MUST derive from the variation's own post ID, never the
    parent's, or every variable product's variations collide into one row.

    Returns (variant_count, orphan_variant_count).
    """
    meta_all = data["meta"]
    ngn = Currency.objects.get(code="NGN")

    term_names = {
        (t["taxonomy"], t["slug"]): t["name"]
        for t in data["terms"]
        if t["taxonomy"].startswith("pa_")
    }
    variations_by_parent: dict[int, list[dict]] = {}
    for v in data["variations"]:
        variations_by_parent.setdefault(v["post_parent"], []).append(v)

    products_by_wp_id = {
        p.legacy_wp_id: p for p in Product.objects.filter(legacy_source=LEGACY_SOURCE)
    }

    count = 0
    orphan_variant_count = 0
    for row in data["products"]:
        wp_id = row["ID"]
        product = products_by_wp_id.get(wp_id)
        if product is None:
            continue
        children = variations_by_parent.get(wp_id, [])
        live_skus: set[str] = set()

        if children:
            # A variation with an empty _weight inherits the parent product's
            # weight -- that is WooCommerce's own semantics, and the merchant set
            # the parent weight precisely BECAUSE it is inherited. Reading only
            # the child's meta left 43 of 122 live variants with no weight at
            # all, and delivery/services.py sums `weight_grams or 0`, so each of
            # them quietly shipped at 0 g. Not replicating the inheritance is the
            # corruption; replicating it is the fix. Woo stores an unset weight
            # as "" rather than NULL, which `or` handles along with None.
            parent_weight = meta_all.get(str(wp_id), {}).get("_weight")
            for position, child in enumerate(children):
                cmeta = meta_all.get(str(child["ID"]), {})
                attrs = {k: v for k, v in cmeta.items() if k.startswith("attribute_")}
                sku = generate_sku(cmeta.get("_sku"), child["ID"])
                variant = _upsert_variant(
                    product=product,
                    sku=sku,
                    name=child["post_title"].split(" - ")[-1],
                    option_values=parse_option_values(attrs, term_names),
                    weight_grams=_grams(cmeta.get("_weight") or parent_weight, sku=sku),
                    is_default=(position == 0),
                    position=position,
                )
                _rewrite_prices(variant, cmeta, ngn, skip_prices)
                live_skus.add(sku)
                count += 1
        else:
            pmeta = meta_all.get(str(wp_id), {})
            sku = generate_sku(pmeta.get("_sku"), wp_id)
            variant = _upsert_variant(
                product=product,
                sku=sku,
                name="Default",
                option_values={},
                weight_grams=_grams(pmeta.get("_weight"), sku=sku),
                is_default=True,
                position=0,
            )
            _rewrite_prices(variant, pmeta, ngn, skip_prices)
            live_skus.add(sku)
            count += 1

        # A variant row from a previous run that is no longer in the source --
        # its variation was deleted in WooCommerce, or its _sku changed so
        # generate_sku now yields a different value for the same underlying
        # variation -- must be deactivated, never deleted: historical order
        # items may reference it, and a re-run must not destroy migrated data.
        # is_default is cleared too, otherwise the row would keep is_default=True
        # from its last live run while the new first variation also becomes the
        # default, leaving two is_default=True rows on one product.
        orphans = product.variants.exclude(sku__in=live_skus)
        for orphan in orphans:
            logger.warning(
                "Variant %s (product %s) is no longer in the source — deactivating",
                orphan.sku, product.slug,
            )
        orphan_variant_count += orphans.update(is_active=False, is_default=False)
    return count, orphan_variant_count


def _upsert_variant(*, product, sku, name, option_values, weight_grams, is_default, position):
    variant, _ = ProductVariant.objects.update_or_create(
        sku=sku,
        defaults={
            "product": product,
            "name": name,
            "option_values": option_values,
            "weight_grams": weight_grams,
            "is_default": is_default,
            "position": position,
        },
    )
    return variant


def _rewrite_prices(variant, meta, currency, skip_prices) -> None:
    """Delete-and-recreate, NOT update-or-skip.

    The unique constraint is (variant, currency, country, starts_at); Postgres
    treats NULL starts_at as distinct, so update-or-skip would stack a fresh
    base price on every run without ever raising.

    Price carries no provenance marker to say "a human edited this row after
    migration" -- adding one is over-engineering for a tool retired at cutover.
    Instead: `--skip-prices` lets a post-cutover corrective run leave pricing
    entirely alone, and any run that touches pricing logs a WARNING when the
    existing amount differs from the incoming one, so there's an audit trail
    even when the flag isn't used.
    """
    if skip_prices:
        return

    regular = _decimal(meta.get("_regular_price"))
    if regular is None:
        return

    existing_base = variant.prices.filter(
        currency=currency, country__isnull=True, starts_at__isnull=True
    ).first()
    if existing_base is not None and existing_base.amount != regular:
        logger.warning(
            "Price divergence for variant %s: existing base amount=%s, incoming=%s "
            "-- the incoming value will overwrite it",
            variant.sku, existing_base.amount, regular,
        )

    sale = _decimal(meta.get("_sale_price"))
    existing_sale = variant.prices.filter(
        currency=currency, country__isnull=True, starts_at__isnull=False
    ).first()
    if existing_sale is not None and sale is not None and existing_sale.amount != sale:
        logger.warning(
            "Price divergence for variant %s: existing sale amount=%s, incoming=%s "
            "-- the incoming value will overwrite it",
            variant.sku, existing_sale.amount, sale,
        )

    variant.prices.filter(currency=currency, country__isnull=True).delete()
    Price.objects.create(variant=variant, currency=currency, amount=regular)

    if sale is None:
        return
    Price.objects.create(
        variant=variant,
        currency=currency,
        amount=sale,
        compare_at_amount=regular,
        starts_at=_epoch(meta.get("_sale_price_dates_from")),
        ends_at=_epoch(meta.get("_sale_price_dates_to")),
    )


def _decimal(raw):
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return Decimal(str(raw)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _grams(raw, *, sku):
    """WooCommerce _weight is in kilograms for this store. Returns None for
    missing/invalid input, meaning "unknown" here -- NOTE this is weaker
    protection than it sounds: apps/delivery/services.py:42 sums
    `v.weight_grams or 0`, so the delivery layer currently treats an unknown
    weight as zero anyway. Measured against the live catalogue 2026-07-26:
    of 122 sellable variants, 71 carry their own _weight, 43 inherit the
    parent's (see the caller), and **8 have no weight anywhere in WordPress**
    and will therefore quote 0 g until a human enters one. Changing that
    delivery math is out of scope for Plan-21, so it's left alone here -- this
    docstring exists only so it doesn't claim a protection the system doesn't
    actually provide.

    Also logs a WARNING (does not clamp or reject) when the converted value
    exceeds 50kg -- almost certainly a kg/g data-entry error upstream (e.g.
    "99999" meant as grams, not kilograms) that would otherwise silently
    distort a shipping quote, worst on Rest-of-World freight.
    """
    if raw is None or str(raw).strip() == "":
        return None
    try:
        grams = int(round(float(str(raw).strip()) * 1000))
    except (TypeError, ValueError):
        return None
    if grams <= 0:
        return None
    if grams > 50_000:
        logger.warning(
            "Variant %s has a suspiciously high weight: %s g (source _weight=%r) "
            "-- check for a kg/g data-entry error",
            sku, grams, raw,
        )
    return grams


def _epoch(raw):
    if not raw or not str(raw).strip().isdigit():
        return None
    return datetime.fromtimestamp(int(raw), tz=dt_timezone.utc)
