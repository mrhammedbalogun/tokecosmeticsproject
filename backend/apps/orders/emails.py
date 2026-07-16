"""Transactional order emails, wired in as the state machine's deferred effects.

Every function here is an EFFECT: it takes an order pk and runs AFTER the transaction
commits (see orders/state.py). That ordering is not incidental — enqueuing inside the
transaction lets the Celery worker read the order before it exists to anyone else.

The context handed to Celery must be JSON-serializable, so it is built here from
committed data rather than passing model instances. Money is rendered through
`format_money`, never `|floatformat`, so a currency's precision has one source of truth.
"""
from __future__ import annotations

from apps.notifications.tasks import send_email_task
from apps.orders.models import Order
from apps.payments.money import format_money


def _context(order: Order) -> dict:
    money = lambda amount: format_money(amount, order.currency)  # noqa: E731
    return {
        "number": order.number,
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


def enqueue_order_confirmation(order_pk: int) -> None:
    """Payment verified and stock committed — the order is real. Fires on ANY move to
    `processing`, which deliberately includes the late-payment `expired -> processing`
    path: that customer paid too, and keying on the destination rather than the pair is
    what stops them being silently skipped.

    There is no separate "payment received" email. With four instant gateways, placement
    and payment are the same moment for the customer, and two mails would land together.
    If a bank-transfer/pay-on-delivery gateway is ever added they become distinct events
    and this splits into `order_received` + `payment_received`.
    """
    _send(order_pk, "order_confirmation")


def enqueue_shipped(order_pk: int) -> None:
    _send(order_pk, "order_shipped")


def enqueue_delivered(order_pk: int) -> None:
    _send(order_pk, "order_delivered")


def enqueue_refund_processed(order_pk: int, amount: str = "") -> None:
    _send(order_pk, "refund_processed", refund_amount=amount)
