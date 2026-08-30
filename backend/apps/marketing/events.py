"""What gets sent, to whom, and whether it is allowed — the policy layer.

The adapters translate; this decides. Keeping the two apart is what lets an adapter be
tested against a fixture with no database, and what keeps "may we send this at all" in
ONE readable place instead of repeated four times with a subtle difference in the third.

── THE FOUR REASONS AN EVENT IS NOT SENT ───────────────────────────────────────────────

  1. `MarketingSettings.tracking_enabled` is off — the master switch.
  2. The channel row is off, or its `server_enabled` is off, or it has no pixel id, or
     its credential is missing from the environment.
  3. The customer did not consent to marketing.
  4. The channel has no server-side sender at all (Google Ads, in v1).

── WHICH OF THOSE IS WORTH A ROW ───────────────────────────────────────────────────────

Only the ones where the channel was SWITCHED ON and the event still did not go: no
consent, no credential, no pixel id, no attribution snapshot. Those are the cases where
somebody will later ask "why is this sale missing from the ad account", and a table that
only records attempts cannot answer them.

A channel that is switched off, or a platform with no server API, or the master switch
being down, writes NOTHING. Those are global states, knowable by looking at the settings
screen, and recording them per order would add four rows to every order for ever and
bury the rows that mean something.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.marketing.credentials import missing_settings_for, supports_server_side
from apps.marketing.models import ConversionEvent, MarketingChannel, MarketingSettings
from apps.marketing.payloads import PURCHASE, ContentItem, ConversionPayload, UserSignals
from apps.marketing.value import currency_code, purchase_value

logger = logging.getLogger(__name__)


def _user_signals(order, attribution) -> UserSignals:
    """Everything the platforms can match on, read out of the order snapshot.

    The ADDRESS SNAPSHOT is the source, not the live `Address` row: a customer may have
    edited or deleted the address since, and the order's own record of where it went is
    both stable and the thing that was true at purchase. Same argument the shipping code
    already makes for `_address_snapshot`.
    """
    address = order.shipping_address or {}
    return UserSignals(
        email=order.email,
        phone=order.phone,
        first_name=address.get("first_name", ""),
        last_name=address.get("last_name", ""),
        city=address.get("area", "") or address.get("city_text", ""),
        state=address.get("state", ""),
        postcode=address.get("postcode", ""),
        country=address.get("country_code", "") or (order.country_id or ""),
        # Account holders only. A guest has no stable id to give — their email already
        # travels, and inventing one per order would tell every platform that every
        # guest order came from a different person, which is worse than saying nothing.
        external_id=str(order.user_id) if order.user_id else "",
        client_ip=attribution.client_ip or "" if attribution else "",
        client_user_agent=attribution.client_user_agent if attribution else "",
        click_ids=(attribution.click_ids if attribution else {}) or {},
        pixel_cookies=(attribution.pixel_cookies if attribution else {}) or {},
    )


def _contents(order) -> tuple[ContentItem, ...]:
    """The order lines, keyed by SKU.

    SKU and not variant id, and this is the decision the whole retargeting half of
    Plan-44 rests on: the product feed publishes SKUs, the browser pixel sends SKUs, and
    this sends SKUs. A platform can only show a visitor the product they viewed if all
    three agree. `OrderItem.sku` is a snapshot that survives the variant being deleted,
    which is exactly what a historical event needs.
    """
    return tuple(
        ContentItem(
            content_id=item.sku or (str(item.variant_id) if item.variant_id else ""),
            quantity=item.quantity,
            item_price=Decimal(item.unit_price),
            name=item.product_name,
        )
        for item in order.items.all()
    )


def purchase_payload(order, attribution=None) -> ConversionPayload:
    """The vendor-neutral Purchase for this order.

    `event_id` is the ORDER NUMBER, and that is the whole deduplication story: the
    browser tag on the confirmation page sends the same string, so a customer who does
    come back from the gateway produces one event, not two. Any other choice — a UUID, a
    timestamp — would need to be communicated between a webhook and a browser that never
    meet.
    """
    return ConversionPayload(
        event_name=PURCHASE,
        event_id=order.number,
        # `placed_at`, not now(): a bank-transfer order confirmed three days later must
        # report the sale at the time it happened, or the platforms attribute it to the
        # wrong day's spend. Every vendor accepts backdated events (Meta up to 7 days),
        # and beyond that window the timestamp is the honest number anyway.
        event_time=int(order.placed_at.timestamp()),
        source_url=(attribution.event_source_url if attribution else ""),
        currency=currency_code(order),
        value=purchase_value(order),
        order_number=order.number,
        contents=_contents(order),
        user=_user_signals(order, attribution),
        ga_client_id=(attribution.pixel_cookies.get("ga", "") if attribution else ""),
    )


def _skip_reason(order, attribution, row) -> str:
    """Why this channel may not have this event, or "" if it may."""
    if not supports_server_side(row.code):
        return "no_server_side_sender"
    if not row.is_enabled:
        return "channel_disabled"
    if not row.server_enabled:
        return "server_side_disabled"
    if not row.pixel_id:
        return "no_pixel_id"
    if row.code == "google_ads" and not (row.server_account_id and row.server_destination_id):
        # Google's server side is addressed separately from its browser tag: without the
        # customer id and the conversion action id there is nowhere to send it, and the
        # API would answer with a validation error per order rather than once.
        return "no_server_destination"
    missing = missing_settings_for(row.code)
    if missing:
        return f"missing_credential:{','.join(missing)}"
    if attribution is None:
        # No snapshot means the order predates Plan-44 or was placed by a path that does
        # not carry one (the admin, an import). Sending anyway would mean asserting a
        # consent nobody recorded.
        return "no_attribution_snapshot"
    if not attribution.consent_marketing:
        return "no_marketing_consent"
    return ""


def enqueue_purchase(order_pk: int) -> None:
    """The `orders.state._effects_for("processing")` effect. Never raises.

    ── WHY IT CANNOT RAISE, AND WHY THAT IS NOT BELT-AND-BRACES ────────────────────────

    `state.py` documents the rule this obeys: `on_commit` callbacks are NOT independent.
    Django's `run_and_clear_commit_hooks` runs them in registration order and one that
    raises abandons every callback after it. This effect is registered LAST in the
    tuple, after the customer's confirmation email and the staff alert — but "last"
    only protects the callbacks before it. Swallowing here is what stops a Meta outage
    from taking down whatever is added after it tomorrow.

    A conversion event is also the least important thing that happens when an order is
    paid. Nothing downstream of this call affects the customer, the stock, or the money.
    """
    try:
        _enqueue_purchase(order_pk)
    except Exception:  # noqa: BLE001 — deliberate; see the docstring
        logger.exception("marketing: failed to enqueue purchase events for order %s", order_pk)


def _enqueue_purchase(order_pk: int) -> None:
    from apps.marketing.tasks import deliver_conversion_event
    from apps.orders.models import Order

    order = Order.objects.select_related("currency", "country").prefetch_related("items").get(
        pk=order_pk
    )
    attribution = getattr(order, "marketing_attribution", None)
    settings_row = MarketingSettings.load()

    if not settings_row.tracking_enabled:
        # The master switch. A global state, not a fact about this order.
        return

    for row in MarketingChannel.objects.all():
        if not supports_server_side(row.code) or not row.is_enabled or not row.server_enabled:
            # Off, or has no server sender at all. Silent by design — see the docstring.
            continue
        reason = _skip_reason(order, attribution, row)
        if reason:
            _record(row.code, order, event_id=order.number, status="skipped", last_error=reason)
            continue

        event = _record(row.code, order, event_id=order.number, status="pending")
        if event is None:
            # Already recorded by an earlier run — the unique constraint did its job.
            continue
        transaction.on_commit(lambda pk=event.pk: deliver_conversion_event.delay(pk))


def _record(channel: str, order, *, event_id: str, status: str,
            last_error: str = "") -> ConversionEvent | None:
    """Write the outbox row, or None when one already exists.

    The unique constraint is the idempotency guarantee and this is where it is honoured
    rather than checked-then-written: a webhook redelivery racing a Celery retry would
    both pass a `filter().exists()` and both send.

    THE ROW IS BORN WITHOUT A PAYLOAD, deliberately. The body is built at delivery time
    from the order and its attribution snapshot, and what is stored afterwards is what
    was ACTUALLY sent. Building it here instead would mean two answers to "what did we
    send" — the one recorded at enqueue and the one the adapter produced from a
    settings row that may have changed in between — and the audit trail would be the
    wrong one of the two.
    """
    try:
        with transaction.atomic():
            return ConversionEvent.objects.create(
                channel=channel, event_name=PURCHASE, event_id=event_id,
                order=order, status=status, last_error=last_error,
            )
    except IntegrityError:
        return None
