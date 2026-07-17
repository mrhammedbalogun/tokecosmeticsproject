"""expire_pending_orders — release stock for pending orders past their reservation TTL.
One transaction PER ORDER (a poison order can't roll back its siblings), each locking
the Order and re-checking status under the lock so it can't race mark_paid. release() is
ledger-idempotent, so a double-run is safe."""
import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.inventory.services import release
from apps.orders.state import transition
from apps.orders.tasks import send_order_expired_manual_email

logger = logging.getLogger(__name__)


def _manual_gateway_codes() -> frozenset[str]:
    """Codes confirmed by a human. Derived once from the registry — NOT get_gateway() per
    order: a migrated order carrying a gateway code the registry never heard of would raise
    UnknownGateway inside the loop, roll back that order, kill the task run, and starve
    every due order behind it on every subsequent beat."""
    from apps.payments.gateways.registry import _REGISTRY

    return frozenset(c for c, g in _REGISTRY.items() if g.confirmation == "manual")


@shared_task
def expire_pending_orders() -> int:
    from apps.orders.models import Order

    now = timezone.now()
    manual = _manual_gateway_codes()
    due_ids = list(
        Order.objects.filter(status="pending_payment", reservation_expires_at__lt=now)
        .values_list("pk", flat=True)
    )
    expired = 0
    for pk in due_ids:
        # Per-order try/except so one poison order cannot starve its siblings — the
        # docstring has always promised this; until now nothing in the loop could raise.
        try:
            with transaction.atomic():
                order = Order.objects.select_for_update().get(pk=pk)
                if order.status != "pending_payment" or order.reservation_expires_at >= now:
                    continue  # a payment landed first, or it's no longer due
                # release() is a synchronous in-transaction effect on purpose: freeing the
                # stock must be atomic with the status flip, so it stays here rather than
                # riding on transition()'s deferred (post-commit) effect lane.
                release(reference=order.reservation_reference)
                transition(order, "expired", message="reservation TTL elapsed — stock released")
                if any(p.gateway in manual for p in order.payments.all()):
                    # Their money may already be in our account — silence is the worst
                    # possible answer. on_commit like every other order email.
                    transaction.on_commit(
                        lambda pk=order.pk: send_order_expired_manual_email.delay(pk)
                    )
                expired += 1
        except Exception:  # noqa: BLE001 — one bad order must not stop the sweep
            logger.exception("expire_pending_orders: order %s failed to expire", pk)
    return expired
