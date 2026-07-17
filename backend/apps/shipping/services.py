"""Freight quote lifecycle. The quote is an OBLIGATION — no money moves here. The
freight cash is recorded separately (a later task) as a Payment."""
from __future__ import annotations

from decimal import Decimal

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
