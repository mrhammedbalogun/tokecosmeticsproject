from celery import shared_task
from django.db.models import F

from apps.inventory.models import StockItem
from apps.notifications.send import send_email


@shared_task
def low_stock_digest() -> int:
    """Email admin a digest of stock items at/below their threshold. Returns the count."""
    from django.conf import settings

    low = list(
        StockItem.objects.select_related("variant", "warehouse")
        .filter(quantity__lte=F("low_stock_threshold"))
        .order_by("warehouse__name", "variant__sku")
    )
    if not low:
        return 0
    rows = [
        {"sku": si.variant.sku, "warehouse": si.warehouse.name, "available": si.available}
        for si in low
    ]
    send_email("low_stock_digest", settings.DEFAULT_FROM_EMAIL, {"rows": rows})
    return len(low)
