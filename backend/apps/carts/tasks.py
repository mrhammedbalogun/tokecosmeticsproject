from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.carts.models import Cart

ABANDON_AFTER = timedelta(hours=3)


@shared_task
def abandon_stale_carts() -> int:
    """Flag active carts untouched for >3h as abandoned. Recovery emails are
    Plan-30; this only marks status so the data accrues. Returns the count."""
    cutoff = timezone.now() - ABANDON_AFTER
    return Cart.objects.filter(status="active", updated_at__lt=cutoff).update(status="abandoned")
