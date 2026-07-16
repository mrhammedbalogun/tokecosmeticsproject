"""expire_pending_orders — release stock for pending orders past their reservation TTL.
One transaction PER ORDER (a poison order can't roll back its siblings), each locking
the Order and re-checking status under the lock so it can't race mark_paid. release() is
ledger-idempotent, so a double-run is safe."""
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.inventory.services import release


@shared_task
def expire_pending_orders() -> int:
    from apps.orders.models import Order

    now = timezone.now()
    due_ids = list(
        Order.objects.filter(status="pending_payment", reservation_expires_at__lt=now)
        .values_list("pk", flat=True)
    )
    expired = 0
    for pk in due_ids:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=pk)
            if order.status != "pending_payment" or order.reservation_expires_at >= now:
                continue  # a payment landed first, or it's no longer due
            release(reference=order.reservation_reference)
            order.status = "expired"
            order.save(update_fields=["status", "updated_at"])
            expired += 1
    return expired
