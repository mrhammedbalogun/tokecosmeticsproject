"""Transactional order emails, wired in as the state machine's deferred effects.

Every function here is an EFFECT: it takes an order pk and runs AFTER the transaction
commits (see orders/state.py). That ordering is not incidental — enqueuing inside the
transaction lets the Celery worker read the order before it exists to anyone else.

The context handed to Celery must be JSON-serializable, so it is built here from
committed data rather than passing model instances. Money is rendered through
`format_money`, never `|floatformat`, so a currency's precision has one source of truth.
"""
from __future__ import annotations

from django.conf import settings

from apps.notifications.tasks import send_email_task
from apps.orders.models import Order
from apps.orders.tokens import make_tracking_token
from apps.payments.money import format_money


def _context(order: Order) -> dict:
    money = lambda amount: format_money(amount, order.currency)  # noqa: E731
    return {
        "number": order.number,
        # Login-free deep link, so the customer can check on their parcel from whatever
        # device they happen to read email on. Redacted view only — see orders/tokens.py.
        "tracking_url": (
            f"{settings.FRONTEND_URL}/orders/{order.number}"
            f"?token={make_tracking_token(order.number)}"
        ),
        "placed_at": order.placed_at.strftime("%d %b %Y"),
        "items": [
            {
                "name": item.product_name,
                "variant": item.variant_name,
                "quantity": item.quantity,
                "line_total": money(item.line_total),
            }
            for item in order.items.all()
        ],
        "subtotal": money(order.subtotal),
        "discount_total": money(order.discount_total) if order.discount_total else "",
        "shipping_total": money(order.shipping_total),
        "tax_total": money(order.tax_total) if order.tax_total else "",
        "grand_total": money(order.grand_total),
        "delivery_option_name": order.delivery_option_name,
        "shipping_address": order.shipping_address,
        "tracking_carrier": order.tracking_carrier,
        "tracking_number": order.tracking_number,
    }


def _send(order_pk: int, template: str, **extra) -> None:
    order = Order.objects.select_related("currency").prefetch_related("items").get(pk=order_pk)
    send_email_task.delay(template, order.email, {**_context(order), **extra})


def enqueue_order_received(order_pk: int, bank_details: dict | None = None) -> None:
    """Placement, for gateways that hand the customer payment instructions rather than
    taking the money there and then (`InitiateResult.action == "bank_details"`).

    This is the customer's only durable copy of the account number and — critically — of
    the order number they're told to quote as the transfer reference. Without it those
    details exist solely in the checkout response, and a transfer with no reference is
    exactly the kind you can't match to an order.

    Instant gateways deliberately send nothing here: that customer is mid-redirect, owes
    nothing on paper, and would get two mails seconds apart.
    """
    _send(order_pk, "order_received", **(bank_details or {}))


def enqueue_order_confirmation(order_pk: int) -> None:
    """Payment verified and stock committed — the order is real. Fires on ANY move to
    `processing`, which deliberately includes the late-payment `expired -> processing`
    path: that customer paid too, and keying on the destination rather than the pair is
    what stops them being silently skipped.

    For an instant gateway this is the customer's only email, so it doubles as the
    "payment received" notice — placement and payment are one moment for them. A
    bank-transfer customer gets `order_received` at placement and this one when the money
    is confirmed, which is the two-step the spec's five-email list was describing.
    """
    _send(order_pk, "order_confirmation")


def enqueue_shipped(order_pk: int) -> None:
    _send(order_pk, "order_shipped")


def enqueue_delivered(order_pk: int) -> None:
    _send(order_pk, "order_delivered")


def enqueue_refund_processed(order_pk: int, amount: str = "") -> None:
    _send(order_pk, "refund_processed", refund_amount=amount)
