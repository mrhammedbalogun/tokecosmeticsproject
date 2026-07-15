"""The ONLY code allowed to change stock numbers. Every function runs inside a
transaction and locks StockItem rows in pk order (deadlock-safe), then allocates
by warehouse priority. release/commit_sale replay the movement ledger for
idempotency. A DB CHECK constraint (0 <= reserved <= quantity) is the backstop.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import F, Sum

from apps.inventory.models import StockItem, StockMovement, Warehouse


class InsufficientStock(Exception):
    """Raised when the requested quantity exceeds available stock for a country."""


def available_for_country(variant, country) -> int:
    agg = StockItem.objects.filter(
        variant=variant, warehouse__is_active=True, warehouse__serves_countries=country
    ).aggregate(total=Sum(F("quantity") - F("reserved")))
    return agg["total"] or 0


def _held_reserved(reference: str, stock_item_id: int) -> int:
    """Net reserved currently held under `reference` for one stock item = sum of all
    delta_reserved movements (reservation:+, release:-, sale:-)."""
    agg = StockMovement.objects.filter(
        reference=reference, stock_item_id=stock_item_id
    ).aggregate(s=Sum("delta_reserved"))
    return agg["s"] or 0


def _lock_items(variant, warehouses):
    """Lock the variant's StockItem rows for these warehouses, in pk order.
    pk order (NOT priority order) is load-bearing: it gives a single, consistent
    lock-acquisition order across concurrent reservations, eliminating ABBA
    deadlocks. Allocation re-sorts by priority afterward. Do not 'simplify' this.
    `of=("self",)` locks only StockItem rows, not the joined warehouse rows.
    """
    return list(
        StockItem.objects.select_for_update(of=("self",))
        .select_related("warehouse")
        .filter(variant=variant, warehouse__in=warehouses)
        .order_by("pk")
    )


def reserve(variant, qty: int, country, reference: str) -> None:
    if qty <= 0:
        raise ValueError("qty must be positive")
    warehouses = Warehouse.objects.filter(is_active=True, serves_countries=country)
    with transaction.atomic():
        items = _lock_items(variant, warehouses)
        # Idempotency: already reserved under this reference -> no-op (checked under lock).
        if StockMovement.objects.filter(
            reference=reference, reason="reservation", stock_item__in=items
        ).exists():
            return
        if sum(i.available for i in items) < qty:
            raise InsufficientStock(
                f"Need {qty} of {variant.sku} for {country.code}, "
                f"only {sum(i.available for i in items)} available."
            )
        # Allocate walking warehouses by priority (then pk for stability).
        items.sort(key=lambda i: (i.warehouse.priority, i.pk))
        remaining = qty
        for item in items:
            if remaining <= 0:
                break
            take = min(item.available, remaining)
            if take <= 0:
                continue
            item.reserved += take
            item.save(update_fields=["reserved", "updated_at"])
            StockMovement.objects.create(
                stock_item=item, delta_reserved=take, reason="reservation", reference=reference
            )
            remaining -= take


def _replay(reference: str, *, commit: bool) -> None:
    """Shared release/commit body. For each stock item touched by `reference`,
    compute the still-held reserved and settle it. commit=True also reduces quantity."""
    item_ids = list(
        StockMovement.objects.filter(reference=reference)
        .values_list("stock_item_id", flat=True)
        .distinct()
    )
    with transaction.atomic():
        items = (
            StockItem.objects.select_for_update(of=("self",))
            .filter(pk__in=item_ids)
            .order_by("pk")
        )
        for item in items:
            held = _held_reserved(reference, item.pk)
            if held <= 0:
                continue  # already released/committed -> idempotent no-op
            item.reserved -= held
            if commit:
                item.quantity -= held
                item.save(update_fields=["reserved", "quantity", "updated_at"])
                StockMovement.objects.create(
                    stock_item=item, delta_reserved=-held, delta_quantity=-held,
                    reason="sale", reference=reference,
                )
            else:
                item.save(update_fields=["reserved", "updated_at"])
                StockMovement.objects.create(
                    stock_item=item, delta_reserved=-held, reason="release", reference=reference
                )


def release(reference: str) -> None:
    _replay(reference, commit=False)


def commit_sale(reference: str) -> None:
    _replay(reference, commit=True)


def reconcile(stock_item) -> bool:
    """Invariant check: the ledger sums must equal the live counters. Returns True if
    consistent. Holds only when the item's whole history is movements (started at 0)."""
    agg = StockMovement.objects.filter(stock_item=stock_item).aggregate(
        q=Sum("delta_quantity"), r=Sum("delta_reserved")
    )
    return (agg["q"] or 0) == stock_item.quantity and (agg["r"] or 0) == stock_item.reserved


def adjust(stock_item, new_quantity: int, reason: str, note: str, user=None) -> None:
    """Set on-hand to an absolute value, recording the delta as a movement."""
    if new_quantity < 0:
        raise ValueError("quantity cannot be negative")
    with transaction.atomic():
        locked = StockItem.objects.select_for_update().get(pk=stock_item.pk)
        delta = new_quantity - locked.quantity
        locked.quantity = new_quantity
        locked.save(update_fields=["quantity", "updated_at"])
        StockMovement.objects.create(
            stock_item=locked, delta_quantity=delta, reason=reason, note=note, created_by=user
        )
