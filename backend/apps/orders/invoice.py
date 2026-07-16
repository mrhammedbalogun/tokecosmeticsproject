"""Invoice rendering.

Invoices are generated ON DEMAND and never stored. A PDF written to S3 at fulfilment
keeps asserting the original total long after a refund has changed the commercial
reality, and every future event that invalidates it becomes something a human must
remember to re-trigger. Rendering at request time means the document cannot go stale.
WeasyPrint renders one order in well under a second, so the CPU cost is noise.

The split here is deliberate: `render_invoice_html` holds all the logic and runs
anywhere, while `render_invoice_pdf` is a thin wrapper around WeasyPrint, whose native
Pango/cairo libraries exist on the Linux deploy target but not on a Windows dev box.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.template.loader import render_to_string
from django.utils import timezone

from apps.payments.money import format_money


def _refund_total(order) -> Decimal:
    """Only SETTLED refunds count. A refund still in flight is not money back yet, and an
    invoice that says otherwise is a document the customer can hold us to."""
    from apps.payments.models import Refund

    return Refund.objects.filter(payment__order=order, status="succeeded").aggregate(
        s=Sum("amount")
    )["s"] or Decimal("0")


def invoice_context(order) -> dict:
    money = lambda amount: format_money(amount, order.currency)  # noqa: E731
    refunded = _refund_total(order)
    # Coerce via str for the same reason money.to_minor does: an unsaved instance can
    # still be carrying the str it was constructed with, and float artifacts are worse.
    grand_total = Decimal(str(order.grand_total))
    return {
        "order": order,
        "number": order.number,
        "placed_at": order.placed_at,
        "email": order.email,
        "billing_address": order.billing_address or order.shipping_address,
        "shipping_address": order.shipping_address,
        "delivery_option_name": order.delivery_option_name,
        "items": [
            {
                "name": item.product_name,
                "variant": item.variant_name,
                "sku": item.sku,
                "quantity": item.quantity,
                "unit_price": money(item.unit_price),
                "line_total": money(item.line_total),
            }
            for item in order.items.all()
        ],
        "subtotal": money(order.subtotal),
        "discount_total": money(order.discount_total) if order.discount_total else "",
        "shipping_total": money(order.shipping_total),
        "tax_total": money(order.tax_total) if order.tax_total else "",
        "grand_total": money(grand_total),
        "refunded": money(refunded) if refunded else "",
        "net_paid": money(grand_total - refunded) if refunded else "",
        # NOT placed_at: refunds settle after the order is placed, so dating the refund
        # position from the order date would claim it was accurate before it could be.
        "rendered_at": timezone.now(),
    }


def render_invoice_html(order) -> str:
    return render_to_string("invoice/invoice.html", invoice_context(order))


def render_invoice_pdf(order) -> bytes:
    """HTML -> PDF. Imported lazily so the rest of the orders app (and its tests) stay
    importable on a machine without WeasyPrint's native libraries installed."""
    from weasyprint import HTML

    return HTML(string=render_invoice_html(order)).write_pdf()
