"""Freight quote lifecycle. The quote is an OBLIGATION — no money moves here. The
freight cash is recorded separately (a later task) as a Payment."""
from __future__ import annotations

import hashlib
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.orders.state import record_event


class ShippingError(Exception):
    def __init__(self, code: str, detail: str = "", http: int = 400):
        self.code = code
        self.detail = detail or code
        self.http = http
        super().__init__(self.detail)


def _append_note(quote, text: str) -> None:
    """APPEND, never assign. Re-quoting overwrites `amount`; this is the only trail of
    what was promised before. An earlier bug in this codebase lost money by assigning
    over an earlier flag instead of appending."""
    stamp = timezone.now().strftime("%Y-%m-%d %H:%M")
    quote.note = f"{quote.note}\n[{stamp}] {text}".strip()


def quote_freight(quote, *, staff_user, amount: Decimal, note: str = "") -> None:
    """Record what the forwarder quoted and move to `quoted`. Re-quoting a `quoted` row
    is allowed and expected ("can you try someone cheaper?")."""
    if quote.is_settled:
        raise ShippingError("quote_already_settled",
                            f"This freight quote is already {quote.status}.")
    if amount <= Decimal("0"):
        raise ShippingError("invalid_amount", "A freight quote must be greater than zero.")

    previous = f" (was {quote.amount})" if quote.amount is not None else ""
    quote.amount = amount
    quote.status = "quoted"
    quote.quoted_at = timezone.now()
    _append_note(quote, f"quoted {amount} {quote.currency_id}{previous} by "
                        f"{staff_user.get_username()}: {note}")
    quote.save(update_fields=["amount", "status", "quoted_at", "note", "updated_at"])
    record_event(quote.order, "freight_quoted", actor=staff_user,
                 message=f"{amount} {quote.currency_id}: {note}")


def waive_freight(quote, *, staff_user, note: str) -> None:
    """Merchant absorbs the freight. Requires a PRIOR QUOTE: waiving an unquoted charge
    records nothing, which is the off-books hole this design closes. It must read
    "₦18,400 of freight forgiven", never silence.

    Every escape hatch in this codebase gets worn smooth. The mandatory reason is table
    stakes; the reporting line (added in docs later) is what makes this safe."""
    if quote.is_settled:
        raise ShippingError("quote_already_settled",
                            f"This freight quote is already {quote.status}.")
    if quote.amount is None:
        raise ShippingError(
            "quote_required_before_waive",
            "Quote the freight first, so the waiver records what was forgiven.",
        )
    if not note.strip():
        raise ShippingError("reason_required", "A reason is required to waive freight.")

    quote.status = "waived"
    quote.settled_at = timezone.now()
    _append_note(quote, f"waived {quote.amount} {quote.currency_id} by "
                        f"{staff_user.get_username()}: {note}")
    quote.save(update_fields=["status", "settled_at", "note", "updated_at"])
    record_event(quote.order, "freight_waived", actor=staff_user,
                 message=f"{quote.amount} {quote.currency_id} forgiven: {note}")


def record_freight_receipt(quote, *, staff_user, amount_received: Decimal,
                           bank_reference: str, note: str = "") -> None:
    """Record the freight cash that landed. Creates a Payment(purpose="freight").

    Deliberately does NOT call payments.services.confirm_manual_receipt. That service
    owns the goods leg's controls (three-way amount match, accept_discrepancy, the
    duplicate-reference check) and those controls must stay untouchable by freight.
    The isolation here comes from the CODE PATH, not from the table.

    quoted != received is NORMAL and raises nothing: an intl wire quoted at €40 lands
    ~€32 after correspondent fees. `quote.amount` is what we asked for; `payment.amount`
    is cash. Flagging that gap would fire the review flag on every single RoW order and
    train staff to dismiss it — the failure mode payments.W001 already demonstrates.
    """
    from apps.payments.models import Payment

    if quote.is_settled:
        raise ShippingError("quote_already_settled",
                            f"This freight quote is already {quote.status}.")
    if quote.amount is None:
        raise ShippingError("quote_required_before_receipt",
                            "Quote the freight before recording a receipt against it.")
    if amount_received <= Decimal("0"):
        raise ShippingError("invalid_amount", "A freight receipt must be greater than zero.")

    # One unit of work: the Payment (money) and the quote settlement must both land or
    # neither. ATOMIC_REQUESTS only covers HTTP callers — a shell/Celery caller is
    # unprotected, and a Payment booked while the quote stays `quoted` would let a retry
    # with a different reference double-book freight.
    with transaction.atomic():
        Payment.objects.create(
            order=quote.order,
            gateway="bank_transfer",
            purpose="freight",
            amount=amount_received,          # cash that LANDED, not what was quoted
            currency=quote.currency,
            status="succeeded",              # the transfer already happened; no pending phase
            gateway_reference=bank_reference,
            # gateway_reference (128 chars) is the real dedup key via the unique
            # (gateway, gateway_reference) constraint. This key only needs to be bounded:
            # idempotency_key is varchar(64) and Postgres enforces it, so hash the
            # reference rather than embed it (a long ref would overflow and 500 in prod).
            idempotency_key=(
                f"freight:{quote.order.number}:"
                f"{hashlib.sha1(bank_reference.encode()).hexdigest()[:16]}"
            ),
        )
        quote.status = "paid"
        quote.settled_at = timezone.now()
        _append_note(quote, f"received {amount_received} {quote.currency_id} "
                            f"(ref {bank_reference}) by {staff_user.get_username()}: {note}")
        quote.save(update_fields=["status", "settled_at", "note", "updated_at"])
        record_event(quote.order, "freight_received", actor=staff_user,
                     message=f"{amount_received} {quote.currency_id} (ref {bank_reference})")
