from celery import shared_task
from django.conf import settings

from apps.core.models import SiteSetting
from apps.delivery.gig.client import GigError
from apps.delivery.gig.coverage import sync_gig_coverage
from apps.notifications.send import send_email


@shared_task
def sync_gig_coverage_task() -> dict:
    """Nightly GIG coverage sweep (Plan-32a slice 2). A GIG outage makes tonight's
    sync a no-op, not a crash loop: yesterday's coverage keeps serving checkout,
    which fails toward "offer GIG where we last knew it worked" — the quote call
    itself is the real-time gate."""
    try:
        return sync_gig_coverage()
    except GigError as exc:
        return {"skipped": f"GIG unavailable: {exc}"}


@shared_task
def poll_gig_tracking() -> dict:
    """Every 2h until GIG's webhook exists; the fallback after. Outage = skipped
    pass; the shipments keep their last known scan and the next pass catches up."""
    from apps.delivery.gig.tracking import poll_tracking

    try:
        return poll_tracking()
    except GigError as exc:
        return {"skipped": f"GIG unavailable: {exc}"}


# SiteSetting, not the cache, for the digest's reason (inventory/tasks.py): LocMemCache
# is per-process, and two workers would each alert as if the other hadn't.
_WALLET_ALERT_STATE_KEY = "delivery.gig_wallet_alert.state"


@shared_task
def monitor_gig_wallet() -> dict:
    """The wallet is prepaid and debited at waybill creation, so an empty wallet
    halts the packing bench, not checkout — invisible until someone is standing
    at it. This alerts on the CROSSING into low (once, not every 6 hours of
    still-low), and re-arms when the balance recovers above the threshold.

    A null balance (GIG reports none for some accounts) alerts nobody: unknown
    is not low, and the capture-time live check is the guard that matters."""
    from apps.delivery.gig.capture import wallet_balance

    try:
        balance = wallet_balance(refresh=True)
    except GigError as exc:
        return {"skipped": f"GIG unavailable: {exc}"}
    if balance is None:
        return {"balance": None}

    threshold = settings.GIG_WALLET_ALERT_THRESHOLD
    state = "low" if balance < threshold else "ok"
    row = SiteSetting.objects.filter(key=_WALLET_ALERT_STATE_KEY).first()
    previous = row.value if row else "ok"
    if state == "low" and previous != "low":
        send_email(
            "gig_wallet_low",
            settings.DEFAULT_FROM_EMAIL,
            {"balance": balance, "threshold": threshold},
        )
    if state != previous:
        SiteSetting.objects.update_or_create(
            key=_WALLET_ALERT_STATE_KEY, defaults={"value": state, "value_type": "str"}
        )
    return {"balance": str(balance), "state": state, "alerted": state == "low" and previous != "low"}
