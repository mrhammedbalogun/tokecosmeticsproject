"""Scheduled order housekeeping."""
import logging

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.orders.emails import enqueue_order_expired_manual
from apps.orders.models import Order
from apps.orders.state import IllegalTransition, transition

logger = logging.getLogger(__name__)


@shared_task
def send_order_expired_manual_email(order_pk: int) -> None:
    """Tell a bank-transfer customer their lapsed reservation was released.

    A task rather than a direct emails.enqueue_* call from the sweep, because the sweep is
    itself a beat task processing many orders: a template render or a mail-backend hiccup
    on one customer's email must not surface as a failure of the sweep that already
    committed their expiry.
    """
    enqueue_order_expired_manual(order_pk)


def _complete_one(pk: int) -> bool:
    """Complete a single delivered order, re-checking under the lock."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=pk)
        if order.status != "delivered":
            return False  # a refund or a staff action got there first
        try:
            transition(
                order,
                "completed",
                message=f"return window closed ({settings.RETURN_WINDOW_DAYS} days since delivery)",
            )
        except IllegalTransition:
            return False
        return True


@shared_task
def complete_delivered_orders() -> int:
    """Close out orders whose return window has elapsed.

    Staff can complete an order sooner from the admin — whichever happens first wins.
    Without this backstop every order parks at `delivered` forever and `completed` stops
    meaning anything, which matters because Plan-11's verified-purchase review rule and
    Plan-28's accounting both read it.

    The clock runs from the DELIVERY event, not `placed_at`: an order that took three
    weeks to arrive has not had its return window run down by the shipping time.

    One transaction PER ORDER, mirroring expire_pending_orders: a poison order must not
    roll back its siblings or abort the sweep.
    """
    cutoff = timezone.now() - timezone.timedelta(days=settings.RETURN_WINDOW_DAYS)
    due = list(
        Order.objects.filter(
            status="delivered",
            events__type="status:delivered",
            events__created_at__lt=cutoff,
        )
        .values_list("pk", flat=True)
        .distinct()
    )
    completed = 0
    for pk in due:
        try:
            if _complete_one(pk):
                completed += 1
        except Exception:  # noqa: BLE001 — one bad order must not stop the sweep
            logger.exception("auto-complete failed for order %s", pk)
    return completed
