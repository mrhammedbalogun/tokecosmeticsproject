from celery import shared_task
from django.db.models import F

from apps.inventory.csv_io import import_stock_csv, parse_csv_bytes
from apps.inventory.models import StockItem
from apps.notifications.models import resolve_recipients
from apps.notifications.staff import notify_staff


@shared_task
def import_stock_csv_task(raw_bytes: bytes, user_id=None, dry_run: bool = False) -> dict:
    user = None
    if user_id:
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(pk=user_id).first()
    return import_stock_csv(parse_csv_bytes(raw_bytes), user=user, dry_run=dry_run)


# Where the last-sent digest's fingerprint lives. `SiteSetting` rather than the cache
# deliberately: `CACHE_BACKEND` is unset in production, so the default is LocMemCache —
# per-process, which means two Celery workers would each believe they had never sent
# anything and the de-duplication would silently do nothing. A row survives restarts,
# deploys and worker count.
_DIGEST_STATE_KEY = "inventory.low_stock_digest.last_signature"


def _signature(rows: list[dict]) -> str:
    """A stable fingerprint of WHICH items are low, and which have run out.

    Membership, not quantity: an item drifting 5 → 4 → 3 within the low band is the same
    news three times, and re-sending it is precisely what trains somebody to filter this
    mail. Hitting ZERO is different — it changes what a customer can buy — so it is part
    of the fingerprint and re-alerts.
    """
    return "|".join(
        f"{r['sku']}@{r['warehouse']}{'!' if r['available'] <= 0 else ''}"
        for r in sorted(rows, key=lambda r: (r["warehouse"], r["sku"]))
    )


@shared_task
def low_stock_digest() -> int:
    """Email admin a digest of stock items at/below their threshold, ONLY WHEN IT CHANGES.

    ── WHY THIS IS NOT SENT EVERY RUN ──────────────────────────────────────────────

    This runs hourly. With no stock in the system that was harmless; with a real
    catalogue and a handful of chronically low SKUs it would send the identical list 24
    times a day, and the reliable result of that is a rule in somebody's mail client that
    hides the one message that mattered.

    The cadence is deliberately NOT demoted to daily. The spam came from repetition, not
    from frequency — an hourly check that only speaks when something changed tells you a
    bestseller ran out within the hour, which a daily digest cannot. Returns the number of
    low rows found, whether or not anything was sent, so the beat log still shows the
    position.
    """
    from apps.core.models import SiteSetting

    low = list(
        StockItem.objects.select_related("variant", "warehouse")
        .filter(quantity__lte=F("low_stock_threshold"))
        .order_by("warehouse__name", "variant__sku")
    )
    rows = [
        {"sku": si.variant.sku, "warehouse": si.warehouse.name, "available": si.available}
        for si in low
    ]

    signature = _signature(rows)
    previous = SiteSetting.objects.filter(key=_DIGEST_STATE_KEY).first()
    last_signature = previous.value if previous else ""

    if signature == last_signature:
        return len(rows)

    # Recovery is worth recording but not worth an email: "nothing is low any more" is
    # good news nobody needs interrupting for, and the state is reset so the next dip
    # sends again.
    if not rows:
        SiteSetting.objects.update_or_create(
            key=_DIGEST_STATE_KEY, defaults={"value": "", "value_type": "str"}
        )
        return 0

    # What is new since the last message, so the mail leads with the change rather than
    # making somebody diff two lists by eye.
    previously = set(last_signature.split("|")) if last_signature else set()
    newly = [
        r for r in rows
        if f"{r['sku']}@{r['warehouse']}{'!' if r['available'] <= 0 else ''}" not in previously
    ]

    # Addressed to the "Low stock" subscriber list, NOT `DEFAULT_FROM_EMAIL`. It was
    # the latter until 2026-08-16, which meant every digest since this task shipped went
    # to `hello@mg.tokecosmetics.com` — the Resend SENDING subdomain, which has no
    # inbox. The alert has never reached a person. See `apps/notifications/events.py`.
    sent = notify_staff(
        "inventory.low_stock",
        {"rows": rows, "newly_low": newly, "is_first": not last_signature},
    )

    # THE SIGNATURE IS ONLY RECORDED IF SOMETHING ACTUALLY WENT OUT. This task is
    # edge-triggered: writing the signature means "they have been told", and it silences
    # the digest until the low LIST changes. Writing it unconditionally would turn one
    # broker blip into a digest nobody ever receives — the SKUs stay low, the list stays
    # identical, and the next 24 runs an hour compare equal and send nothing.
    #
    # Nobody subscribed is NOT a failure to retry: `sent == 0` there is a configuration
    # the Owner chose on the Email Notifications screen, and re-sending on every run
    # would not reach them either. Leaving the state unwritten in that case would just
    # mean re-rendering an email into the void hourly, so only a genuine enqueue failure
    # (subscribers exist, none could be queued) holds the state back.
    if sent or not resolve_recipients("inventory.low_stock"):
        SiteSetting.objects.update_or_create(
            key=_DIGEST_STATE_KEY, defaults={"value": signature, "value_type": "str"}
        )
    return len(rows)
