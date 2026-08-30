"""Delivery of conversion events, and the retention sweep for the personal data they use.

The delivery task is the only place in this app that touches the network.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

# How long a failed event is worth retrying. Meta accepts events up to 7 DAYS late and
# the others are similarly generous, so the constraint is not the vendors' patience —
# it is that an event nobody has managed to deliver in half an hour is failing for a
# reason a retry will not fix (a revoked token, a deleted pixel), and a worker that
# keeps trying is a worker not sending today's sales.
MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 300

# The attribution snapshot keeps an IP address and a user agent because every platform's
# match algorithm wants them. 90 days is past the longest attribution window any of the
# four uses (Meta's is 28 days for reporting, 7 for optimisation), so after it the two
# columns are personal data being kept for no purpose — which is the definition of what
# should not be kept. The click ids stay: they identify an ad click, not a person.
PII_RETENTION_DAYS = 90


@shared_task(bind=True, max_retries=MAX_RETRIES, default_retry_delay=RETRY_DELAY_SECONDS)
def deliver_conversion_event(self, event_pk: int) -> dict:
    """Send one outbox row to its platform.

    Rebuilds the body here rather than reading one stored at enqueue time, so what is
    recorded on the row afterwards is what actually went over the wire — see
    `events._record`.

    Retries only what the adapter calls retryable. A 400 from Meta means the body is
    wrong and will be wrong in five minutes too; retrying it would turn one broken
    payload into five identical failures and hide the real error behind the last one.
    """
    from apps.marketing.channels.registry import build_channel
    from apps.marketing.events import purchase_payload
    from apps.marketing.models import ConversionEvent, MarketingChannel
    from apps.marketing.payloads import PURCHASE

    event = ConversionEvent.objects.select_related("order").filter(pk=event_pk).first()
    if event is None:
        return {"event": event_pk, "skipped": "row_gone"}
    if event.status == "sent":
        # A duplicate task for an already-delivered event. Not an error: Celery
        # guarantees at-least-once, and this is the "at least" part arriving.
        return {"event": event_pk, "skipped": "already_sent"}
    if event.order is None:
        _fail(event, "order_deleted", retryable=False)
        return {"event": event_pk, "failed": "order_deleted"}

    row = MarketingChannel.objects.filter(code=event.channel).first()
    if row is None or not row.is_enabled:
        # Switched off between enqueue and delivery. Honour the newer decision: the
        # Owner turning a channel off means "stop sending", including the backlog.
        event.status = "skipped"
        event.last_error = "channel_disabled_before_delivery"
        event.save(update_fields=["status", "last_error", "updated_at"])
        return {"event": event_pk, "skipped": "channel_disabled"}

    channel = build_channel(row)
    if channel is None:
        _fail(event, "no_server_side_sender", retryable=False)
        return {"event": event_pk, "failed": "no_server_side_sender"}

    if event.event_name != PURCHASE:
        # Only purchase is server-side today. A row for anything else is a bug in
        # whatever wrote it, and failing loudly beats sending a half-built body.
        _fail(event, f"unsupported_event:{event.event_name}", retryable=False)
        return {"event": event_pk, "failed": "unsupported_event"}

    attribution = getattr(event.order, "marketing_attribution", None)
    body = channel.build(purchase_payload(event.order, attribution))
    result = channel.send(body)

    event.attempts += 1
    event.payload = body
    event.response_excerpt = result.excerpt[:2000]
    if result.ok:
        event.status = "sent"
        event.sent_at = timezone.now()
        event.last_error = ""
        event.save(update_fields=["attempts", "payload", "response_excerpt", "status",
                                  "sent_at", "last_error", "updated_at"])
        return {"event": event_pk, "sent": True, "channel": event.channel}

    event.last_error = f"status={result.status} {result.excerpt}"[:2000]
    if result.retryable and self.request.retries < MAX_RETRIES:
        event.status = "pending"
        event.save(update_fields=["attempts", "payload", "response_excerpt", "status",
                                  "last_error", "updated_at"])
        raise self.retry(countdown=RETRY_DELAY_SECONDS * (self.request.retries + 1))

    event.status = "failed"
    event.save(update_fields=["attempts", "payload", "response_excerpt", "status",
                              "last_error", "updated_at"])
    logger.warning("marketing: %s event %s failed permanently: %s",
                   event.channel, event.event_id, event.last_error)
    return {"event": event_pk, "sent": False, "channel": event.channel}


def _fail(event, reason: str, *, retryable: bool) -> None:
    event.status = "pending" if retryable else "failed"
    event.last_error = reason
    event.attempts += 1
    event.save(update_fields=["status", "last_error", "attempts", "updated_at"])


@shared_task
def purge_attribution_pii() -> dict:
    """Clear the IP address and user agent from attribution snapshots older than the
    longest attribution window, and blank the stored payloads that copied them.

    The event payloads matter as much as the source row: a delivered Meta body carries
    `client_ip_address` and `client_user_agent` in the clear, so purging only
    `OrderAttribution` would leave the same two facts sitting in `ConversionEvent`.
    Clearing the payload keeps the row — the status, the response, the timestamps are
    the audit trail and none of them is personal data.
    """
    from apps.marketing.models import ConversionEvent, OrderAttribution

    cutoff = timezone.now() - timedelta(days=PII_RETENTION_DAYS)

    attributions = OrderAttribution.objects.filter(
        created_at__lt=cutoff, pii_purged_at__isnull=True
    )
    rows = attributions.update(
        client_ip=None, client_user_agent="", pii_purged_at=timezone.now()
    )

    payloads = ConversionEvent.objects.filter(
        created_at__lt=cutoff
    ).exclude(payload={}).update(payload={})

    return {"attributions_purged": rows, "payloads_cleared": payloads}
