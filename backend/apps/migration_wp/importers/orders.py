"""WooCommerce orders -> orders.Order + OrderItem + OrderEvent (Plan-23).

Idempotent on `(source, legacy_number)`. Safe to re-run for the rehearsal, the cutover
delta and any corrective pass.

── WHAT THIS IMPORTER DELIBERATELY DOES NOT DO ──────────────────────────────────────────

* **It never touches stock.** Every one of these 4,096 orders was fulfilled or abandoned
  in WooCommerce years or months ago. Calling `commit_sale`/`reserve` would drive live
  inventory to nonsense on the first run. `Order`/`OrderItem` rows are written directly.
* **It never creates a `Payment` row.** `_refund_owned_by_the_ledger`
  (`orders/views.py:205-218`) says in as many words that a legacy order "has no captured
  payment here", and the admin's manual-refund transition depends on that. Inventing
  `succeeded` payments for the 1,185 paid legacy orders would make every one of them
  refuse the manual transition and demand a gateway refund against a gateway this platform
  has never talked to. How they paid is recorded as an `OrderEvent` instead — history, in
  the append-only place built for history.
* **It never recomputes money.** Totals are copied from WooCommerce. See
  `transform_orders.subtotal_from` for the one derived figure and why.
* **It never matches a registered order to an account by email.** See `_resolve_user`.
"""

from __future__ import annotations

from decimal import Decimal

from apps.accounts.models import LegacyIdentity
from apps.catalog.models import Product, ProductVariant
from apps.core.models import Country, Currency
from apps.migration_wp.importers.common import logger
from apps.migration_wp.transform_orders import (
    GATEWAY_NAMES,
    address_snapshot,
    map_status,
    money,
    order_number,
    subtotal_from,
)
from apps.orders.models import Order, OrderEvent, OrderItem

#: Where an order lands when its billing country is missing or unknown. `Order.country` is
#: a PROTECT FK and cannot be null, so there has to be an answer; these are the stores'
#: home markets, and the raw billing country is preserved in the address snapshot either
#: way, so nothing is lost.
STORE_DEFAULT_COUNTRY = {
    "legacy_ng": "NG",
    "legacy_ng_old": "NG",
    "legacy_intl": "GB",
}


def _resolve_user(row, identities: dict[int, object]):
    """(user, email). A registered order links through LegacyIdentity; a guest never does.

    THE EMAIL FALLBACK IS FOR GUESTS ONLY, and that restriction is a security control, not
    a nicety. `architecture.md` §"Legacy guest-order claiming" requires migrated guest
    orders to land `user=None` with the real email, so that `claims.py` can attach them
    later — but only after the account proves it controls that inbox. Matching a
    *registered* order to whoever holds that address in Django today would hand a
    stranger's order history and PII to a registrant, which is the exact attack claiming
    was written to refuse.
    """
    email = (row.get("billing_email") or "").strip().lower()
    customer_id = int(row.get("customer_id") or 0)
    if customer_id > 0:
        user = identities.get(customer_id)
        # A registered order whose customer never migrated (deleted in WordPress, or below
        # the >=1-order bar) lands as a guest: user=None, email kept. It is still their
        # order and they can still claim it by verifying the address.
        return user, (email or (getattr(user, "email", "") or ""))
    return None, email


def _variant_for(item_meta: dict, products_by_wp_id: dict, variants_by_sku: dict):
    """Best-effort link to a live ProductVariant. None is an acceptable answer.

    106 NG line items carry no `_product_id` at all, and orders reference products that no
    longer exist in the catalogue. An unresolvable line becomes an item with no variant
    link rather than a dropped line: dropping it would change the order total and make the
    migrated order disagree with the invoice the customer is holding.
    """
    sku = (item_meta.get("_sku") or "").strip()
    if sku and sku in variants_by_sku:
        return variants_by_sku[sku]

    for key in ("_variation_id", "_product_id"):
        try:
            wp_id = int(item_meta.get(key) or 0)
        except (TypeError, ValueError):
            continue
        product = products_by_wp_id.get(wp_id)
        if product is not None:
            return (
                product.variants.filter(is_default=True).first()
                or product.variants.order_by("position", "id").first()
            )
    return None


def import_orders(data: dict, *, since=None) -> dict:
    """Import one store's order artifact. Returns a counts-only summary."""
    store = data["store"]
    rows = data["orders"]
    addresses = data.get("addresses", {})
    items_by_order = data.get("items", {})

    identities = {
        li.wp_user_id: li.user
        for li in LegacyIdentity.objects.filter(store=store).select_related("user")
    }
    products_by_wp_id = {
        p.legacy_wp_id: p for p in Product.objects.exclude(legacy_wp_id=None)
    }
    variants_by_sku = {v.sku: v for v in ProductVariant.objects.all() if v.sku}
    currencies = {c.code: c for c in Currency.objects.all()}
    countries = {c.code: c for c in Country.objects.all()}

    created = updated = 0
    skipped_trashed: list[int] = []
    skipped_before_since = 0
    flagged: list[int] = []
    unlinked_items = 0
    guest_orders = 0
    missing_currency: list[int] = []

    for row in rows:
        wp_id = int(row["id"])
        number = order_number(store, wp_id)
        legacy_number = str(wp_id)

        created_at = row.get("date_created_gmt")
        if since and (str(created_at or "") < since):
            skipped_before_since += 1
            continue

        paid = bool(row.get("date_paid_gmt"))
        status, review_reason = map_status(row.get("status"), paid=paid)
        if status is None:
            skipped_trashed.append(wp_id)
            continue

        currency = currencies.get((row.get("currency") or "").upper())
        if currency is None:
            # Without a currency the money is meaningless, and Order.currency is a PROTECT
            # FK. Skipping loudly beats inventing an exchange rate.
            missing_currency.append(wp_id)
            continue

        addr = addresses.get(str(wp_id)) or addresses.get(wp_id) or {}
        billing = address_snapshot(addr.get("billing"))
        shipping = address_snapshot(addr.get("shipping")) if addr.get("shipping") else billing

        country_code = (billing.get("country") or "").upper() or STORE_DEFAULT_COUNTRY[store]
        country = countries.get(country_code) or countries.get(STORE_DEFAULT_COUNTRY[store])
        if country is None:
            missing_currency.append(wp_id)
            continue

        user, email = _resolve_user(row, identities)
        if user is None:
            guest_orders += 1

        totals = {
            "total_amount": row.get("total_amount"),
            "tax_amount": row.get("tax_amount"),
            "shipping_total_amount": row.get("shipping_total_amount"),
            "discount_total_amount": row.get("discount_total_amount"),
        }

        order = Order.objects.filter(source=store, legacy_number=legacy_number).first()
        if order is None:
            order = Order(number=number, source=store, legacy_number=legacy_number)
            is_new = True
        else:
            is_new = False

        order.user = user
        order.email = email
        order.phone = (billing.get("phone") or "")[:32]
        order.country = country
        order.currency = currency
        order.status = status
        order.review_reason = review_reason
        order.subtotal = subtotal_from(totals)
        order.discount_total = money(totals["discount_total_amount"])
        order.shipping_total = money(totals["shipping_total_amount"])
        order.tax_total = money(totals["tax_amount"])
        order.grand_total = money(totals["total_amount"])
        order.billing_address = billing
        order.shipping_address = shipping
        order.customer_note = (row.get("customer_note") or "")[:2000]
        if created_at:
            order.placed_at = created_at
        order.save()

        if review_reason:
            flagged.append(wp_id)

        # Items are rewritten wholesale on a re-run rather than diffed: they are immutable
        # history, and a diff would be more code with more ways to be wrong.
        order.items.all().delete()
        raw_items = items_by_order.get(str(wp_id)) or items_by_order.get(wp_id) or []
        for item in raw_items:
            if item.get("order_item_type") != "line_item":
                continue  # shipping/tax/coupon lines are already in the order totals
            meta = item.get("meta") or {}
            variant = _variant_for(meta, products_by_wp_id, variants_by_sku)
            if variant is None:
                unlinked_items += 1
            try:
                quantity = max(int(float(meta.get("_qty") or 1)), 1)
            except (TypeError, ValueError):
                quantity = 1
            line_total = money(meta.get("_line_total"))
            OrderItem.objects.create(
                order=order,
                variant=variant,
                product_name=(item.get("order_item_name") or "")[:255],
                variant_name=(variant.name if variant else "")[:255],
                sku=(meta.get("_sku") or (variant.sku if variant else ""))[:64],
                # quantity is >=1 by construction above, so this cannot divide by zero.
                unit_price=(line_total / quantity).quantize(Decimal("0.01")),
                line_total=line_total,
                quantity=quantity,
            )

        if is_new:
            created += 1
            gateway = (row.get("payment_method") or "").strip()
            title = (row.get("payment_method_title") or "").strip()
            OrderEvent.objects.create(
                order=order,
                type="migrated",
                message=(
                    f"Imported from WooCommerce ({store}, order #{wp_id}). "
                    f"Paid by {title or gateway or 'unrecorded method'}"
                    f"{f' [{GATEWAY_NAMES.get(gateway, gateway)}]' if gateway else ''}"
                    f"{' on ' + str(row['date_paid_gmt']) if paid else ' — never paid'}. "
                    "No payment record was migrated: there is no captured money on this "
                    "platform to refund."
                ),
            )
        else:
            updated += 1

    summary = {
        "store": store,
        "rows": len(rows),
        "created": created,
        "updated": updated,
        "guest_orders": guest_orders,
        "flagged_for_review": len(flagged),
        "line_items_without_a_variant": unlinked_items,
        "skipped_trashed": len(skipped_trashed),
        "skipped_no_currency_or_country": len(missing_currency),
        "skipped_before_since": skipped_before_since,
        # WordPress ids only — never emails. Same PII rule as Plan-22.
        "sample_flagged_wp_ids": flagged[:20],
        "sample_skipped_trashed_wp_ids": skipped_trashed[:20],
        "sample_skipped_no_currency_wp_ids": missing_currency[:20],
    }
    logger.info("import_orders %s: %s", store, summary)
    return summary
