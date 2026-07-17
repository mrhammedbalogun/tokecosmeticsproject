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
  _react_to_verdict(payment, outcome) -> bool
                                  — the recovery ladder: re-reserve on expiry, flag
                                    double-payments and payments-on-cancelled-orders for
                                    review. Reports whether the order ended up fulfilled,
                                    which the verdict alone cannot say. Shared by every
                                    confirmation path so none of them can drift.
  confirm_payment(payment)        — the ONLY thing webhook processing and the client
                                    return endpoint call. Verifies with the gateway
                                    (network, OUTSIDE any transaction), checks amount +
                                    currency, then hands the verdict to the ladder.
  confirm_manual_receipt(payment) — the other entry point, for gateways with no machine to
                                    ask (bank transfer). A staff member reading the bank
                                    statement supplies the amount instead of verify(), and
                                    the same ladder takes it from there.
"""
from __future__ import annotations

import enum
import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from apps.inventory.models import StockMovement
from apps.inventory.services import InsufficientStock, commit_sale, release, reserve
from apps.orders.models import Order
from apps.orders.state import transition
from apps.payments.models import Payment
from apps.payments.money import from_minor, to_minor

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


def _append_reason(order, reason: str) -> bool:
    """Add `reason` to the in-memory order's review_reason, unless it's already there.
    Returns whether anything changed; the CALLER saves, because callers who already hold
    the row lock must not re-open a transaction just to write a note.

    Every writer of review_reason goes through here. It is not a formatting helper: a
    writer that assigns directly erases whatever an earlier writer put there, which is the
    whole failure this exists to prevent (see _flag_review)."""
    reasons = [r for r in order.review_reason.split("; ") if r]
    if reason in reasons:
        return False
    reasons.append(reason)
    order.review_reason = "; ".join(reasons)
    return True


def _flag_review(order_id: int, reason: str) -> None:
    """Flag an order for human attention. `review_reason` is the single source of truth
    and is ORTHOGONAL to the lifecycle: "a human must look at this" is not a place in the
    order's life, it's a note pinned to it. A processing order can need review (the
    double-payment case) and so can an expired one, so the status is left alone —
    it keeps saying what actually happened, and no information is destroyed.

    Only an explicit admin resolve action clears this (see orders.state), never a
    status transition — otherwise shipping a flagged order would silently erase an
    unresolved double-payment and nobody would ever refund the customer.

    APPENDS rather than assigns, for the same reason: an order accumulates unresolved facts
    over its life, and while this assigned, whichever writer came second erased the first —
    leaving staff to act on the survivor alone. A mismatch flagged while pending_payment,
    then a late payment that can't re-reserve, used to leave only "could not re-reserve
    stock": staff refund the order total, never learning the gateway reported a different
    amount. The fact that explained WHY the money was in dispute was the one erased.

    resolve_review still clears the whole string in one explicit act, so Plan-10's model is
    untouched — an admin decides everything here is handled, not a passing writer."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if not _append_reason(order, reason):
            return  # already flagged for exactly this — replays are normal here
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
                _append_reason(
                    order, f"payment {payment.pk} received on a cancelled order — refund it"
                )
            else:
                _append_reason(
                    order,
                    f"late payment {payment.pk}: order moved to {order.status} while "
                    "confirming — a human must decide whether to fulfil or refund",
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
            _append_reason(
                order,
                f"late payment {payment.pk} after expiry — could not re-reserve stock: {exc}",
            )
            order.save(update_fields=["review_reason", "updated_at"])
            logger.warning("Order %s: late payment could not re-reserve: %s", order.number, exc)
            return
        order.reservation_reference = new_ref
        order.save(update_fields=["reservation_reference", "updated_at"])
        _fulfil_locked(order, payment)


def _react_to_verdict(payment, outcome: MarkPaidResult) -> bool:
    """React to mark_paid's verdict. Returns whether the order ended up FULFILLED.

    Shared by BOTH confirmation paths (gateway verify and manual receipt) — the recovery
    logic for late/cancelled/duplicate money is identical regardless of who did the
    verifying, and a copy-paste would let one path silently stop recovering money.

    The return value matters: NOOP_EXPIRED may or may not end in fulfilment depending on
    whether _reserve_and_fulfil_after_expiry could re-reserve stock, and callers that flag
    an amount discrepancy must only do so when the goods actually shipped — otherwise they
    append noise to the ladder's own, more urgent, instruction (see _flag_review).
    """
    if outcome is MarkPaidResult.FULFILLED:
        return True

    if outcome is MarkPaidResult.NOOP_EXPIRED:
        _reserve_and_fulfil_after_expiry(payment.order, payment)
        payment.refresh_from_db(fields=["status"])
        return payment.status == "succeeded"  # succeeded <=> fulfilled, by invariant

    if outcome is MarkPaidResult.NOOP_CANCELLED:
        _flag_review(
            payment.order_id,
            f"payment {payment.pk} received on a cancelled order — refund it",
        )
        return False

    # NOOP_ALREADY_PROCESSED: either an idempotent replay of THIS payment, or a second,
    # distinct payment for an order another payment already fulfilled (double charge).
    payment.refresh_from_db(fields=["status"])
    if payment.status == "succeeded":
        return True  # this payment already fulfilled the order — benign replay
    _flag_review(
        payment.order_id,
        f"possible double payment — order already processing; refund payment {payment.pk}",
    )
    return False


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
    _react_to_verdict(payment, mark_paid(payment))


# --- confirm_manual_receipt: the fulfilment entry point for bank transfer ----


class AmountDiscrepancy(Exception):
    """The confirmed amount is not the order total and staff did not explicitly accept it.
    Nothing was fulfilled. Carries the numbers so the caller can show them and come back."""

    def __init__(self, expected: Decimal, received: Decimal):
        self.expected, self.received = expected, received
        super().__init__(f"received {received}, order is owed {expected}")


class DuplicateBankReference(Exception):
    """This bank reference already confirmed another order — one statement line cannot pay
    for two orders. Override with allow_duplicate_reference=True."""


def _find_duplicate_reference(payment, bank_reference: str):
    """Another payment already confirmed against this statement line, if any. The cheapest
    fraud control we have: one transfer quoted as the reference for two orders would
    otherwise ship goods twice against money that arrived once."""
    return (
        Payment.objects.filter(
            gateway=payment.gateway,
            raw_response__manual_receipt__has_key=bank_reference,
        )
        .exclude(pk=payment.pk)
        .select_related("order")
        .first()
    )


def confirm_manual_receipt(
    payment,
    *,
    staff_user,
    amount_received: Decimal,
    bank_reference: str,
    note: str = "",
    accept_discrepancy: bool = False,
    allow_duplicate_reference: bool = False,
) -> None:
    """Fulfil an order whose money arrived by bank transfer. The staff member reading the
    bank statement IS the verification — there is no gateway to ask — so this deliberately
    does NOT call verify(). It reuses mark_paid and the shared verdict ladder, because the
    recovery logic for late/cancelled/duplicate money doesn't care who did the verifying.

    Any nonzero delta requires accept_discrepancy + a reason. Overpayment then fulfils and
    flags the surplus for refund (they paid enough — don't hold their goods hostage);
    shortfall then fulfils and records who accepted it (intl wires legitimately lose a
    slice to intermediary banks). Without the flag an unexpected amount raises, because the
    common cause is a typo and the resulting flag is the ONLY authorisation a human needs
    to wire real money out.
    """
    from apps.orders.state import record_event
    from apps.payments.gateways.registry import get_gateway

    if get_gateway(payment.gateway).confirmation != "manual":
        # Letting staff hand-wave a Stripe payment into 'succeeded' would break
        # succeeded <=> money-actually-arrived.
        raise ValueError(
            f"{payment.gateway} is machine-confirmed — use confirm_payment(), not manual receipt"
        )

    expected_minor = to_minor(payment.amount, payment.currency)
    received_minor = to_minor(amount_received, payment.currency)
    delta = received_minor - expected_minor

    if delta and not accept_discrepancy:
        record_event(
            payment.order, "manual_receipt_refused", actor=staff_user,
            message=(
                f"refused: {amount_received} {payment.currency_id} against "
                f"{payment.amount} (ref {bank_reference})"
            ),
        )
        # Deliberately NO review flag: nothing happened, and the caller already has the
        # numbers. A flag here would outlive the corrected confirm that follows.
        raise AmountDiscrepancy(payment.amount, amount_received)

    if delta and not note.strip():
        raise ValueError("accepting an amount discrepancy requires a reason")

    if not allow_duplicate_reference:
        other = _find_duplicate_reference(payment, bank_reference)
        if other is not None:
            raise DuplicateBankReference(
                f"bank reference {bank_reference} already confirmed order {other.order.number}"
            )

    # Keyed by reference rather than replaced: two staff confirming concurrently both save
    # here unlocked, and last-write-wins would leave the payment recording an amount that
    # fulfilled nothing. The OrderEvents are the audit trail; this is the ledger detail.
    receipts = dict((payment.raw_response or {}).get("manual_receipt", {}))
    receipts[bank_reference] = {
        "amount_received": str(amount_received),
        "confirmed_by": staff_user.get_username(),
        "note": note,
        "accept_discrepancy": accept_discrepancy,
    }
    payment.raw_response = {**(payment.raw_response or {}), "manual_receipt": receipts}
    payment.save(update_fields=["raw_response", "updated_at"])

    fulfilled = _react_to_verdict(payment, mark_paid(payment))

    # AFTER mark_paid, with the outcome: recording "confirmed" before it would have a
    # losing racer claim credit for a confirmation that did nothing.
    record_event(
        payment.order, "payment_confirmed_manually", actor=staff_user,
        message=(
            f"{amount_received} {payment.currency_id} confirmed against bank reference "
            f"{bank_reference} — {'fulfilled' if fulfilled else 'no fulfilment (see flags)'}"
            + (f" — {note}" if note else "")
        ),
    )

    if not fulfilled:
        # The ladder already flagged the operative instruction (refund it / could not
        # re-reserve). A delta flag here would append noise to an unresolved, more urgent
        # fact — or worse, imply the goods shipped.
        return

    if delta > 0:
        _flag_review(
            payment.order_id,
            f"overpaid by {from_minor(delta, payment.currency)} {payment.currency_id} "
            f"(received {amount_received} against {payment.amount}) — refund the difference",
        )
    elif delta < 0:
        _flag_review(
            payment.order_id,
            f"shortfall of {from_minor(-delta, payment.currency)} {payment.currency_id} "
            f"accepted by {staff_user.get_username()}: {note} "
            f"(received {amount_received} against {payment.amount})",
        )
