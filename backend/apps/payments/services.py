"""The money-confirmation core.

Three layers, so the amount check and the recovery logic never pollute the tiny
idempotent fulfilment primitive:

  _fulfil_locked(order, payment)  — assumes the order row is locked and the reservation
                                    under order.reservation_reference is valid. Pure DB.
  mark_paid(payment) -> MarkPaidResult
                                  — locks the order, fulfils iff pending_payment, and
                                    REPORTS what it found (never silently no-ops). The
                                    invariant: payment.status == "succeeded" is written
                                    ONLY here (via _fulfil_locked).
  confirm_payment(payment)        — the ONLY thing webhook processing and the client
                                    return endpoint call. Verifies with the gateway
                                    (network, OUTSIDE any transaction), checks amount +
                                    currency, then reacts to mark_paid's verdict:
                                    re-reserve on expiry, flag double-payments and
                                    payments-on-cancelled-orders for review.
"""
from __future__ import annotations

import enum
import logging

from django.db import transaction
from django.db.models import Sum

from apps.inventory.models import StockMovement
from apps.inventory.services import InsufficientStock, commit_sale, release, reserve
from apps.orders.models import Order
from apps.orders.state import transition
from apps.payments.money import to_minor

logger = logging.getLogger(__name__)

# Statuses where the order is already fulfilled (or beyond) — a late payment landing on
# one of these has nothing left to do. ("partially_refunded" is absent deliberately: it is
# no longer a status, since a partial refund is a ledger fact, not a lifecycle move.)
_FULFILLED_STATES = frozenset({"processing", "shipped", "delivered", "completed", "refunded"})


class MarkPaidResult(enum.Enum):
    FULFILLED = "fulfilled"
    NOOP_ALREADY_PROCESSED = "noop_already_processed"
    NOOP_EXPIRED = "noop_expired"
    NOOP_CANCELLED = "noop_cancelled"


def _fulfillment_by_warehouse(reference: str) -> dict:
    """From the reservation ledger: {warehouse_name: qty} for this reference."""
    rows = (
        StockMovement.objects.filter(reference=reference, reason="reservation")
        .values("stock_item__warehouse__name")
        .annotate(qty=Sum("delta_reserved"))
    )
    return {r["stock_item__warehouse__name"]: r["qty"] for r in rows}


def _fulfil_locked(order, payment) -> None:
    """Commit stock, snapshot fulfilment, redeem coupon, flip payment+order to paid.
    Caller MUST hold the order row lock and guarantee a valid reservation exists under
    order.reservation_reference."""
    commit_sale(reference=order.reservation_reference)

    fulfil = _fulfillment_by_warehouse(order.reservation_reference)
    if fulfil:
        for item in order.items.all():
            item.fulfillment_warehouses = fulfil
            item.save(update_fields=["fulfillment_warehouses"])

    if order.coupon_id:
        from apps.checkout.models import CouponRedemption

        CouponRedemption.objects.get_or_create(
            coupon_id=order.coupon_id, order_number=order.number,
            defaults={"user": order.user, "email": order.email},
        )

    payment.status = "succeeded"
    payment.save(update_fields=["status", "updated_at"])
    order.reservation_expires_at = None
    order.save(update_fields=["reservation_expires_at", "updated_at"])
    # Legal from pending_payment (normal) and from expired (the late-payment re-reserve).
    transition(order, "processing", message=f"payment {payment.pk} verified via {payment.gateway}")


@transaction.atomic
def mark_paid(payment) -> MarkPaidResult:
    """Fulfil the order iff it is still awaiting payment. Idempotent and race-safe vs the
    expiry task via the row lock. Returns a verdict so the caller can recover from the
    non-happy states instead of silently dropping money on the floor."""
    order = Order.objects.select_for_update().get(pk=payment.order_id)
    if order.status == "pending_payment":
        _fulfil_locked(order, payment)
        return MarkPaidResult.FULFILLED
    if order.status == "expired":
        return MarkPaidResult.NOOP_EXPIRED
    if order.status == "cancelled":
        return MarkPaidResult.NOOP_CANCELLED
    return MarkPaidResult.NOOP_ALREADY_PROCESSED


# --- confirm_payment: the single fulfilment entry point for gateways ---------


def _amounts_match(result, payment) -> bool:
    """Verified amount+currency must equal the Payment's (which equals the order total,
    asserted at Payment creation). Compared in integer minor units — never floats."""
    if result.currency != payment.currency_id:
        return False
    return to_minor(result.amount, payment.currency) == to_minor(payment.amount, payment.currency)


def _flag_review(order_id: int, reason: str) -> None:
    """Flag an order for human attention. `review_reason` is the single source of truth
    and is ORTHOGONAL to the lifecycle: "a human must look at this" is not a place in the
    order's life, it's a note pinned to it. A processing order can need review (the
    double-payment case) and so can an expired one, so the status is left alone —
    it keeps saying what actually happened, and no information is destroyed.

    Only an explicit admin resolve action clears this (see orders.state), never a
    status transition — otherwise shipping a flagged order would silently erase an
    unresolved double-payment and nobody would ever refund the customer.

    APPENDS rather than assigns, for the same reason. An order can accumulate several
    unresolved facts in ONE request — the verdict ladder flags "refund the whole payment on
    this cancelled order" and confirm_manual_receipt's delta branch flags "overpaid by X" —
    and while this assigned, whichever wrote second erased the other, leaving staff to act
    on the survivor: refund the ₦2,000 surplus, resolve, and the customer is out the ₦10,000
    the erased flag was about. resolve_review still clears the whole string in one explicit
    act, so Plan-10's model is untouched."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        reasons = [r for r in order.review_reason.split("; ") if r]
        if reason in reasons:
            return  # already flagged for exactly this — replays are normal here
        reasons.append(reason)
        order.review_reason = "; ".join(reasons)
        order.save(update_fields=["review_reason", "updated_at"])
    logger.warning("Order %s flagged for review: %s", order_id, reason)


def _bump_attempt(reference: str) -> str:
    """TC-100042 -> TC-100042/2 -> TC-100042/3. The attempt suffix gives a FRESH ledger
    key so inventory.reserve() (which is reference-idempotent) actually reserves again."""
    base, _, suffix = reference.partition("/")
    n = int(suffix) if suffix else 1
    return f"{base}/{n + 1}"


def _reserve_and_fulfil_after_expiry(order, payment) -> None:
    """Late payment landed after the reservation expired. Re-reserve under a bumped
    attempt suffix and fulfil — all under the order lock. If stock is gone, release the
    partial reservation and flag for review (auto-refund territory)."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status != "expired":
            # Raced between mark_paid's NOOP_EXPIRED verdict and this lock. Re-dispatch on
            # what is ACTUALLY true now — never fall through to re-reserve. On a cancelled
            # order that takes stock for a dead order and then raises IllegalTransition
            # out of the webhook task; on `on_hold` (on_hold -> processing is legal!) it
            # silently commits the same stock twice.
            if order.status in _FULFILLED_STATES:
                return  # another confirm got there first — nothing owed
            if order.status == "cancelled":
                order.review_reason = (
                    f"payment {payment.pk} received on a cancelled order — refund it"
                )
            else:
                order.review_reason = (
                    f"late payment {payment.pk}: order moved to {order.status} while "
                    "confirming — a human must decide whether to fulfil or refund"
                )
            order.save(update_fields=["review_reason", "updated_at"])
            logger.warning(
                "Order %s: late payment raced to %s — flagged", order.number, order.status
            )
            return
        new_ref = _bump_attempt(order.reservation_reference)
        try:
            for item in order.items.all():
                if item.variant_id is None:
                    raise InsufficientStock(f"{order.number}: item variant no longer exists")
                reserve(item.variant, item.quantity, order.country, reference=new_ref)
        except InsufficientStock as exc:
            release(new_ref)  # clean up any items reserved before the failing one
            # Stays `expired` — that IS the truth. review_reason says why a human must
            # look (this is auto-refund territory: we hold their money, not their goods).
            order.review_reason = (
                f"late payment {payment.pk} after expiry — could not re-reserve stock: {exc}"
            )
            order.save(update_fields=["review_reason", "updated_at"])
            logger.warning("Order %s: late payment could not re-reserve: %s", order.number, exc)
            return
        order.reservation_reference = new_ref
        order.save(update_fields=["reservation_reference", "updated_at"])
        _fulfil_locked(order, payment)


def confirm_payment(payment) -> None:
    """Verify with the gateway and fulfil. Safe to call from both the webhook task and
    the customer return endpoint — the row lock makes the race benign (first fulfils,
    second is an idempotent no-op)."""
    from apps.payments.gateways.registry import get_gateway

    result = get_gateway(payment.gateway).verify(payment)  # network — NOT under a lock

    payment.raw_response = {**(payment.raw_response or {}), "verify": result.raw}

    if result.status != "succeeded":
        payment.status = "pending" if result.status == "pending" else "failed"
        payment.save(update_fields=["status", "raw_response", "updated_at"])
        return

    if not _amounts_match(result, payment):
        payment.save(update_fields=["raw_response", "updated_at"])
        _flag_review(
            payment.order_id,
            f"payment {payment.pk}: gateway reported {result.amount} {result.currency}, "
            f"order total is {payment.amount} {payment.currency_id} — not fulfilling",
        )
        return

    payment.save(update_fields=["raw_response", "updated_at"])  # persist verify before fulfilling
    outcome = mark_paid(payment)

    if outcome is MarkPaidResult.FULFILLED:
        return

    if outcome is MarkPaidResult.NOOP_EXPIRED:
        _reserve_and_fulfil_after_expiry(payment.order, payment)
        return

    if outcome is MarkPaidResult.NOOP_CANCELLED:
        _flag_review(
            payment.order_id,
            f"payment {payment.pk} received on a cancelled order — refund it",
        )
        return

    # NOOP_ALREADY_PROCESSED: either an idempotent replay of THIS payment, or a second,
    # distinct payment for an order another payment already fulfilled (double charge).
    payment.refresh_from_db(fields=["status"])
    if payment.status == "succeeded":
        return  # this payment already fulfilled the order — benign replay
    _flag_review(
        payment.order_id,
        f"possible double payment — order already processing; refund payment {payment.pk}",
    )
