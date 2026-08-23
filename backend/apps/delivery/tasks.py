from celery import shared_task
from django.conf import settings

from apps.core.models import SiteSetting
from apps.delivery.gig.client import GigError
from apps.delivery.gig.coverage import sync_gig_coverage
from apps.notifications.models import resolve_recipients
from apps.notifications.staff import notify_staff


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
def sync_gig_centres_task() -> dict:
    """Nightly, same failure posture as the LGA sync: an outage keeps yesterday's
    centre list serving the picker, and the order snapshot is what fulfilment reads."""
    from apps.delivery.gig.centres import sync_gig_centres

    try:
        return sync_gig_centres()
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
        # Subscriber list, not `DEFAULT_FROM_EMAIL` — same fix and same reason as the
        # low-stock digest: the old address is the Resend sending subdomain and has no
        # inbox, so this alert has never reached anybody either.
        #
        # `str(balance)` and not `balance`: this context now crosses into Celery
        # (`CELERY_TASK_SERIALIZER = "json"`), and `wallet_balance()` returns a Decimal,
        # which the JSON serializer refuses. The old direct `send_email` call was
        # synchronous and never had to answer that question. The templates only ever
        # interpolated it, so the rendered mail is unchanged.
        sent = notify_staff(
            "delivery.gig_wallet_low",
            # THOUSAND-SEPARATED HERE, not in the template. `str(Decimal)` renders
            # "12400.00", and the alert's whole job is to make a number legible at a
            # glance in a subject line — "₦50000" and "₦500000" are one careless glance
            # apart. Django has no comma filter without `contrib.humanize`, and adding an
            # app to format one integer is more moving parts than formatting it here.
            # The task's RETURN value keeps `str(balance)` — that is a machine-readable
            # result other code and the tests assert on, not a display string.
            {"balance": f"{balance:,.2f}", "threshold": f"{threshold:,}"},
        )
        # Same edge-trigger reasoning as the low-stock digest, and it matters more here.
        # Recording `state="low"` means "they have been told", and re-arming needs the
        # balance to climb back ABOVE the threshold and dip again. Record that on a run
        # where nothing was queued and the alert is lost until someone happens to top the
        # wallet up — which nobody will, because the alert asking them to is the thing
        # that went missing. Staying "ok" costs one duplicate alert if the next run
        # succeeds; the alternative costs a halted packing bench.
        if not sent and resolve_recipients("delivery.gig_wallet_low"):
            return {"balance": str(balance), "state": previous,
                    "alerted": False, "enqueue_failed": True}
    if state != previous:
        SiteSetting.objects.update_or_create(
            key=_WALLET_ALERT_STATE_KEY, defaults={"value": state, "value_type": "str"}
        )
    return {"balance": str(balance), "state": state, "alerted": state == "low" and previous != "low"}


# --- AAJ Express (Plan-43) -----------------------------------------------------------

@shared_task
def poll_aaj_tracking() -> dict:
    """Every 2h, forever — AAJ has no webhook. Outage = the pass stops at the first
    unreachable call; the shipments keep their last known scan and the next pass
    catches up."""
    from apps.delivery.aaj.client import AajError
    from apps.delivery.aaj.tracking import poll_tracking

    try:
        return poll_tracking()
    except AajError as exc:
        return {"skipped": f"AAJ unavailable: {exc}"}


@shared_task(bind=True, max_retries=3, default_retry_delay=600)
def delete_aaj_booking(self, shipment_pk: int, booking_id: str) -> dict:
    """Best-effort removal of an UNPAID booking at AAJ after its order died
    (aaj/shipments.py). Free, idempotent (a second delete 404s), and never a
    reason to fail the order transition that queued it. Refused once processed —
    that means money moved after all, which the order page's check must settle."""
    from apps.delivery.aaj import client

    try:
        client.call("DELETE", f"/partner/booking/delete-booking/{booking_id}", retries=0)
    except client.AajUnavailable as exc:
        raise self.retry(exc=exc)
    except client.AajError as exc:
        return {"shipment_pk": shipment_pk, "booking_id": booking_id, "deleted": False,
                "reason": str(exc)}
    return {"booking_id": booking_id, "deleted": True}


@shared_task
def check_aaj_states() -> dict:
    """Nightly drift check of `aaj/states.py` against AAJ's own delivery-locations
    list. The table prices every AAJ order and an unknown code silently prices as
    Lagos, so a state AAJ renames or re-codes would undercharge with no signal
    except the bank statement. Mismatch = staff email; outage = skipped."""
    from apps.delivery.aaj import client
    from apps.delivery.aaj.states import STATE_CODES, state_code
    from apps.notifications.staff import notify_staff

    try:
        result = client.call("GET", "/partner/booking/delivery-locations/aaj")
    except client.AajError as exc:
        return {"skipped": f"AAJ unavailable: {exc}"}
    rows = result.data if isinstance(result.data, list) else []
    theirs = {str(r.get("stateCode", "")).upper(): str(r.get("state", "")) for r in rows if isinstance(r, dict)}
    mismatches = []
    for code, name in theirs.items():
        if state_code(name) != code:
            mismatches.append(f"{name} ({code})")
    missing = sorted(set(STATE_CODES.values()) - set(theirs))
    if mismatches or missing:
        notify_staff("delivery.aaj_attention", {
            "order_number": "", "tracking_id": "", "status_label": "",
            "reason": "state code table drift",
            "description": (
                f"AAJ's list disagrees with ours. Unmatched: {', '.join(mismatches) or 'none'}. "
                f"No longer listed by AAJ: {', '.join(missing) or 'none'}. "
                "Until apps/delivery/aaj/states.py is updated, affected states are not quoted."
            ),
        })
    return {"states": len(theirs), "mismatches": mismatches, "missing": missing}
