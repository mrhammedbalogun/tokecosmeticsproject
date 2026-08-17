"""Sending, and honouring, the confirmation link for an external recipient.

The reasoning for why confirmation exists at all is in `models.py`. This module is the
mechanism: mint a link, mail it, and mark the row when somebody comes back.

WHY THE CONFIRM LINK IS NOT SENT THROUGH `notify_staff`. That function fans a
notification out to a subscriber LIST. This is the opposite shape — one message, to one
address, that is not subscribed to anything yet and by construction cannot be, since the
whole point is that it has not been confirmed. Routing it through the subscriber path
would mean an address confirming itself in order to be asked whether it wants to confirm.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from apps.notifications.events import EVENTS_BY_CODE
from apps.notifications.tasks import send_email_task
from apps.notifications.tokens import make_confirm_token

logger = logging.getLogger(__name__)

CONFIRM_TEMPLATE = "recipient_confirm"


def confirm_url_for(recipient) -> str:
    return (
        f"{settings.API_PUBLIC_URL.rstrip('/')}/api/v1/notifications/confirm/"
        f"?token={make_confirm_token(recipient.pk, recipient.email)}"
    )


def send_confirmation(recipient) -> bool:
    """Email `recipient` its confirmation link. Returns whether it was enqueued.

    Refuses staff rows loudly rather than quietly: they are confirmed by construction, so
    a call here means a caller has confused the two row kinds, and mailing a colleague a
    link they do not need is the most confusing possible way to find that out.
    """
    if recipient.user_id is not None:
        logger.error("send_confirmation called for staff row %s", recipient.pk)
        return False

    event = EVENTS_BY_CODE.get(recipient.event)
    context = {
        "address": recipient.email,
        # An address being asked to opt in deserves to know what it is opting into, in the
        # same words the admin screen uses. A bare "confirm your subscription" is how
        # people conclude a mail is phishing and delete it.
        "event_label": event.label if event else recipient.event,
        "event_description": event.description if event else "",
        "confirm_url": confirm_url_for(recipient),
    }
    try:
        send_email_task.delay(CONFIRM_TEMPLATE, recipient.email, context)
    except Exception:  # noqa: BLE001 — broker down; the admin screen offers a resend
        logger.exception("could not enqueue confirmation for recipient %s", recipient.pk)
        return False
    return True


def confirm(recipient) -> int:
    """Confirm `recipient` and every other pending row for the same address. Returns how
    many rows changed.

    CONFIRMATION IS A PROPERTY OF THE ADDRESS, NOT OF ONE SUBSCRIPTION. Rows are keyed
    per (event, email), so subscribing the bookkeeper to two events would otherwise mean
    two near-identical "click to confirm" emails and two clicks — which is both annoying
    and actively harmful, because it trains exactly the click-links-in-unexpected-email
    habit that makes people phishable. One click confirms the address for everything it is
    on, and `inherit_confirmation` gives any LATER subscription the same standing without
    a fresh email.

    What the recipient is consenting to is therefore "notifications from this shop"
    rather than one event, which is what the confirmation page says. For a six-person shop
    with a handful of addresses that is the honest description; if the list ever grows to
    the point where per-event consent matters, this is the function to split.

    IDEMPOTENT, and the first timestamp wins. People click twice, clients prefetch, and a
    back-button re-issues the request; none should move a record of when consent was given.
    """
    from apps.notifications.models import NotificationRecipient

    if not recipient.email:
        return 0
    return NotificationRecipient.objects.filter(
        email=recipient.email, user__isnull=True, confirmed_at__isnull=True
    ).update(confirmed_at=timezone.now())


def inherit_confirmation(recipient) -> bool:
    """Confirm a new row outright if this address has already confirmed another.

    Without this, adding an already-trusted bookkeeper to a second event would mail them
    another confirmation link for an address they confirmed last week — which reads as
    either a bug or a phishing attempt, and is the reason `perform_create` asks this
    before sending anything.
    """
    from apps.notifications.models import NotificationRecipient

    if recipient.user_id is not None or not recipient.email:
        return False
    already = (
        NotificationRecipient.objects.filter(
            email=recipient.email, user__isnull=True, confirmed_at__isnull=False
        )
        .exclude(pk=recipient.pk)
        .order_by("confirmed_at")
        .first()
    )
    if already is None:
        return False
    recipient.confirmed_at = already.confirmed_at
    recipient.save(update_fields=["confirmed_at", "updated_at"])
    return True
