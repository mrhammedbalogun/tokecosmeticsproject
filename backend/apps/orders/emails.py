"""Transactional order emails, wired in as the state machine's deferred effects.

Every function here is an EFFECT: it takes an order pk and runs AFTER the transaction
commits (see orders/state.py). That ordering is not incidental — enqueuing inside the
transaction lets the Celery worker read the order before it exists to anyone else.

The context handed to Celery must be JSON-serializable, so it is built here from
committed data rather than passing model instances. Money is rendered through
`format_money`, never `|floatformat`, so a currency's precision has one source of truth.
"""
from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from apps.catalog.images import storage_url, variant_image_alt, variant_image_path
from apps.notifications.staff import notify_staff
from apps.notifications.tasks import send_email_task
from apps.orders.models import Order
from apps.orders.tokens import make_tracking_token
from apps.payments.labels import gateway_label
from apps.payments.money import format_money, format_percent

logger = logging.getLogger(__name__)


def _items(order: Order) -> list[dict]:
    """The line items, as both the customer and staff templates want them.

    ONE BUILDER FOR BOTH, so a customer's confirmation and the staff alert can never show
    different pictures for the same order.

    THE IMAGE FALLS BACK TO A LIVE LOOKUP when the snapshot is empty. `OrderItem.image_url`
    was declared in orders/0001 and never written until checkout started snapshotting it,
    so every order placed before that carries "" — including every order migrated from
    WooCommerce. Resolving from the `variant` FK covers them. `variant` is SET_NULL, so a
    line whose product has since been deleted simply has no picture, which the templates
    render as a blank cell rather than a broken image.
    """
    rows = []
    for item in order.items.all():
        # The snapshot first, then a live lookup. `image_path` was only written from the
        # day checkout started snapshotting it, so every earlier order — including every
        # one migrated from WooCommerce — carries "" and resolves from the `variant` FK
        # instead. `variant` is SET_NULL, so a line whose product has since been deleted
        # simply has no picture, which the templates render as a blank cell.
        image = storage_url(item.image_path or variant_image_path(item.variant))
        rows.append({
            "name": item.product_name,
            "variant": item.variant_name,
            "quantity": item.quantity,
            "line_total": format_money(item.line_total, order.currency),
            "image": image,
            # Alt text is not decoration here: most mail clients block remote images by
            # default, so for a large share of readers this string IS the picture.
            "image_alt": variant_image_alt(item.variant) or item.product_name,
        })
    return rows


def _context(order: Order) -> dict:
    money = lambda amount: format_money(amount, order.currency)  # noqa: E731
    return {
        "number": order.number,
        # Login-free deep link, so the customer can check on their parcel from whatever
        # device they happen to read email on. Redacted view only — see orders/tokens.py.
        "tracking_url": (
            f"{settings.FRONTEND_URL}/orders/{order.number}"
            f"?token={make_tracking_token(order.number)}"
        ),
        "placed_at": order.placed_at.strftime("%d %b %Y"),
        # Greeting only. Off the shipping-address SNAPSHOT rather than the account, so a
        # guest checkout still gets a name and a later account rename cannot retroactively
        # change what an old email said. Legitimately "" — the templates use it inside a
        # sentence that closes up when it is missing, never in a headline.
        "first_name": (order.shipping_address or {}).get("first_name") or "",
        "items": _items(order),
        "subtotal": money(order.subtotal),
        "discount_total": money(order.discount_total) if order.discount_total else "",
        # The referred customer's own discount, its own line beside the coupon's. "" when
        # there was none, which is what the template's {% if %} keys off.
        "referral_discount_total": (
            money(order.referral_discount_total) if order.referral_discount_total else ""
        ),
        "referral_discount_percent": format_percent(order.referral_discount_percent),
        "shipping_total": money(order.shipping_total),
        "tax_total": money(order.tax_total) if order.tax_total else "",
        "tax_label": order.country.tax_label,
        "grand_total": money(order.grand_total),
        "delivery_option_name": order.delivery_option_name,
        "shipping_address": order.shipping_address,
        # Centre pickup (32b ruling 6): the snapshot from placement, or None for
        # door delivery — templates switch "Delivering to" ↔ "Collect from" on it.
        "pickup_centre": getattr(getattr(order, "gig_shipment", None), "centre", None) or None,
        # Store pickup (Plan-40): the Toke store snapshot from placement, or None.
        # Same template switch as pickup_centre; carries the counter phone because
        # "call the store" is the whole point of printing it.
        "pickup_store": order.pickup_store or None,
        "tracking_carrier": order.tracking_carrier,
        "tracking_number": order.tracking_number,
    }


def _send(order_pk: int, template: str, **extra) -> None:
    order = (
        Order.objects.select_related("currency", "country").prefetch_related("items").get(pk=order_pk)
    )
    send_email_task.delay(template, order.email, {**_context(order), **extra})


def enqueue_order_received(order_pk: int, bank_details: dict | None = None) -> None:
    """Placement, for gateways that hand the customer payment instructions rather than
    taking the money there and then (`InitiateResult.action == "bank_details"`).

    This is the customer's only durable copy of the account number and — critically — of
    the order number they're told to quote as the transfer reference. Without it those
    details exist solely in the checkout response, and a transfer with no reference is
    exactly the kind you can't match to an order.

    Instant gateways deliberately send nothing here: that customer is mid-redirect, owes
    nothing on paper, and would get two mails seconds apart.
    """
    _send(order_pk, "order_received", **(bank_details or {}))


def enqueue_order_confirmation(order_pk: int) -> None:
    """Payment verified and stock committed — the order is real. Fires on ANY move to
    `processing`, which deliberately includes the late-payment `expired -> processing`
    path: that customer paid too, and keying on the destination rather than the pair is
    what stops them being silently skipped.

    For an instant gateway this is the customer's only email, so it doubles as the
    "payment received" notice — placement and payment are one moment for them. A
    bank-transfer customer gets `order_received` at placement and this one when the money
    is confirmed, which is the two-step the spec's five-email list was describing.
    """
    _send(order_pk, "order_confirmation")


def enqueue_shipped(order_pk: int) -> None:
    """The `shipped` move's customer mail — which for a store-pickup order (Plan-40)
    is "ready for pickup", not "on its way". Branching HERE rather than adding a
    status keeps the state machine untouched (Order.status's docstring calls a new
    status the largest blast radius in the design): staff press the same button, the
    machine makes the same move, and the customer reads the mail that is true."""
    if Order.objects.filter(pk=order_pk).exclude(pickup_store={}).exists():
        _send(order_pk, "order_ready_for_pickup")
    else:
        _send(order_pk, "order_shipped")


def enqueue_delivered(order_pk: int) -> None:
    _send(order_pk, "order_delivered")


def enqueue_order_expired_manual(order_pk: int) -> None:
    """A bank-transfer order whose 24h reservation lapsed before anyone matched a payment
    to it. Sent ONLY for manual gateways: a card that never completed means the customer
    never sent money and has nothing to be told.

    This customer might have wired the money and be waiting — the transfer may already be
    in our account, unmatched. Letting the order die in silence is how a paying customer
    ends up with neither goods nor a refund, so this mail exists to hand them the one
    string that unpicks it: their order number.
    """
    _send(order_pk, "order_expired_manual")


def enqueue_refund_processed(order_pk: int, amount: str = "") -> None:
    _send(order_pk, "refund_processed", refund_amount=amount)


# ── STAFF NOTIFICATIONS ─────────────────────────────────────────────────────────────
#
# Everything above this line emails the CUSTOMER. Everything below emails whoever the
# Owner has subscribed on the admin's Email Notifications screen
# (`apps/notifications/models.py`), and the two must not share a context dict.
#
# WHY A SEPARATE CONTEXT AND NOT `_context()` MINUS A FIELD. Two things in the customer
# context must never reach a staff mailing list, and neither is obvious at the call site:
#
# 1. `tracking_url` embeds a signed, login-free bearer token for that order
#    (`orders/tokens.py`). A subscriber list can contain bare addresses with no account
#    behind them, so reusing the customer context would post a working credential to
#    an address that was never invited to anything.
# 2. `shipping_address` is the customer's full street address, and `Order.phone` sits
#    one attribute away from any future edit to this function.
#
# So the staff context is built from scratch and carries the LEAST that answers "is
# there something for me to do?": who it is for, what was ordered, what it is worth, how
# it was paid, how it is being delivered, and the town. A staff member who needs the
# doorstep address logs in — the link is right there in the mail. That keeps a
# compromised bookkeeper's inbox worth a list of order numbers and names rather than a
# customer address book.
#
# THE NAME WAS ADDED DELIBERATELY (2026-08-18, owner's request) and is the one place the
# line moved. It is written on the parcel and said aloud on the phone; a packer who has
# to open the admin to learn whose box this is has lost the trip the alert exists to
# save. `_customer_name` explains why it never falls back to the email address, which
# would have widened this without a decision.

def _staff_local(when) -> str:
    """A timestamp as the person reading it experiences it, or "" for None.

    `TIME_ZONE` is UTC (`config/settings/base.py`) and the people reading these alerts
    are in Lagos, an hour ahead. The customer emails sidestep this by printing only the
    date; a staff alert prints the time, and the awaiting-transfer one asks the reader to
    reason about a deadline from it. An order placed 10:00 WAT that reads "09:00" sends
    whoever is matching bank statements to the wrong hour of the day.
    """
    if when is None:
        return ""
    try:
        when = timezone.localtime(when, ZoneInfo(settings.STAFF_DISPLAY_TIMEZONE))
    except Exception:  # noqa: BLE001 — unknown zone name, or a container with no tzdata
        # Degrade to UTC rather than raise. `_notify_safely` would otherwise swallow the
        # error and silently drop EVERY staff alert over a presentation setting; an hour's
        # offset on a timestamp is a far smaller problem than that.
        logger.warning("STAFF_DISPLAY_TIMEZONE %r is unusable; falling back to UTC",
                       settings.STAFF_DISPLAY_TIMEZONE)
    return when.strftime("%d %b %Y, %H:%M")


def _staff_context(order: Order) -> dict:
    money = lambda amount: format_money(amount, order.currency)  # noqa: E731
    gig = getattr(order, "gig_shipment", None)
    centre = getattr(gig, "centre", None)
    return {
        "number": order.number,
        "placed_at": _staff_local(order.placed_at),
        # THE REAL DEADLINE, not prose. The awaiting-transfer mail used to say "expires 24
        # hours after it was placed", which is wrong the moment a customer retries payment:
        # `retry_payment` pushes `reservation_expires_at` forward (never back) when the new
        # gateway holds stock longer, so the stated deadline would understate the real one
        # and staff would write off an order that was still live. Blank for an order with
        # no reservation, which the template renders as nothing rather than as "None".
        "expires_at": _staff_local(order.reservation_expires_at),
        # Deep link into the ADMIN, not the storefront. Keyed by number because that is
        # what `admin/src/app/(shell)/orders/[number]` routes on.
        "admin_url": f"{settings.ADMIN_URL}/orders/{order.number}",
        "items": _items(order),
        "item_count": sum(item.quantity for item in order.items.all()),
        "grand_total": money(order.grand_total),
        "currency": order.currency_id,
        "country": order.country.name,
        "delivery_option_name": order.delivery_option_name,
        # WHO IT IS FOR. Asked for by the owner (2026-08-18) and a deliberate widening of
        # the line drawn in the note above: a name is not an address. It is what is
        # written on the parcel, it is what a customer says on the phone when they chase
        # an order, and without it staff had to open the admin to answer "whose is this?"
        # — which is exactly the trip this alert exists to save. The street line, the
        # phone number and the tracking token stay out.
        "customer_name": _customer_name(order),
        # HOW THEY PAID. `bank_transfer` reads very differently from `paystack` on a new
        # order: one means the money has cleared, the other means somebody must still
        # match a transfer. Staff were inferring it from which of the two alerts arrived,
        # which stops working the moment a third payment route exists.
        "payment_method": _payment_method(order),
        # Town and region only — see the note above on why the street line is absent.
        "destination": _destination_line(order, centre),
        "is_pickup": bool(centre) or bool(order.pickup_store),
        # What the customer said at checkout. Staff act on this ("gift wrap", "call
        # before delivery"), so an alert that omitted it would send them to the admin
        # for the one field that changes what they do next.
        "customer_note": order.customer_note,
        # A flagged order needs a human before it needs a packer, and the flag is the
        # single most important thing the mail can say.
        "review_reason": order.review_reason,
    }


def _customer_name(order: Order) -> str:
    """The buyer's name from the address SNAPSHOT, or "" when nobody gave one.

    The snapshot rather than `order.user`: a guest checkout has no user at all, and for
    one that does, a later account rename would retroactively change who an old alert
    said the parcel was for. The snapshot is what was written on the box.

    Shipping first, then billing — a "ship to someone else" order should name the person
    receiving the parcel, which is who the packer and the courier deal with.

    NEVER falls back to `order.email`. An email address is a contact identifier and it is
    not in this mail today; quietly substituting one for a missing name would widen what
    a subscribed address holds without anyone deciding to. "" is honest, and the template
    drops the row.
    """
    for snapshot in (order.shipping_address, order.billing_address):
        parts = (snapshot or {}).get("first_name", ""), (snapshot or {}).get("last_name", "")
        name = " ".join(part for part in parts if part).strip()
        if name:
            return name
    return ""


def _payment_method(order: Order) -> str:
    """How this order was paid, as a label, or "" when no payment exists yet.

    A SETTLED payment wins over a newer unsettled one. An order can carry several rows —
    a card attempt that failed and a bank transfer that worked, or a retry through a
    second gateway (`checkout.py::retry_payment`) — and "most recent" would then name the
    gateway that did NOT take the money. The succeeded row is the one that answers "how
    did this money arrive?"; the latest row answers it only while none has succeeded,
    which is precisely the awaiting-transfer case.

    FREIGHT ROWS ARE EXCLUDED. `purpose="freight"` is a separate charge for shipping
    (`shipping/services.py::record_freight_receipt`) and naming its gateway here would
    answer a question nobody asked with the wrong payment entirely.

    Filters in PYTHON, not the ORM: `payments` is prefetched by `_staff_order`, and a
    `.filter()` on the manager would discard that cache and re-query per alert.
    """
    goods = [p for p in order.payments.all() if p.purpose == "goods"]
    if not goods:
        return ""
    settled = [p for p in goods if p.status in ("succeeded", "refunded", "partially_refunded")]
    chosen = max(settled or goods, key=lambda p: p.created_at)
    return gateway_label(chosen.gateway)


def _destination_line(order: Order, centre) -> str:
    """Where it is going, at town resolution. Never the street line.

    A GIG pickup centre's address is a PUBLIC depot address, not a customer's home, so it
    is safe to state in full and useless if abbreviated — the packer needs to know which
    depot the parcel is routed to.

    `centre` IS A DICT, not a `GigCentre`. `GigShipment.centre` is a JSONField holding
    `{"id", "name", "address"}` snapshotted at placement, because centres close and move
    and the parcel must ship to the one that was priced. Attribute access on it raises —
    caught by `test_pickup_confirmation_email_says_collect_from`, which is the only test
    in the suite that routes an order through a pickup centre.
    """
    if centre:
        name = centre.get("name") or "Pickup centre"
        address = centre.get("address") or ""
        return f"{name} (pickup)" + (f" — {address}" if address else "")

    # Store pickup (Plan-40): our OWN shop's address — public by definition, and the
    # packer needs to know which counter this box must be waiting on.
    if order.pickup_store:
        name = order.pickup_store.get("name") or "Toke store"
        address = order.pickup_store.get("address") or ""
        return f"{name} (store pickup)" + (f" — {address}" if address else "")

    # TWO SNAPSHOT SHAPES EXIST IN THIS TABLE, and reading the wrong keys is a bug this
    # codebase has already shipped once — see the comment at the top of
    # `templates/email/_address.txt`, where four templates and the invoice all printed a
    # street line and nothing else because they guessed `city`/`region`.
    #
    # * Orders placed through checkout carry `area` (the town) and `state`
    #   (`checkout/services/checkout.py::_address_snapshot`).
    # * Orders migrated from WooCommerce carry `city` and `state`
    #   (`migration_wp/transform_orders.py::address_snapshot`).
    #
    # Neither writes `region`. Reading both spellings for the town is what makes this
    # line say something for a migrated order as well as a new one; `order.country.name`
    # is the FK and is always right.
    address = order.shipping_address or {}
    town = address.get("area") or address.get("city") or ""
    parts = [town, address.get("state"), order.country.name]
    return ", ".join(part for part in parts if part)


def enqueue_staff_order_paid(order_pk: int) -> None:
    """Fires on ANY move to `processing`, sharing the customer's confirmation hook.

    ONE KNOWN IMPRECISION, accepted deliberately. `_effects_for` keys on the DESTINATION
    status and hands effects nothing but a pk, so this cannot tell `pending_payment ->
    processing` (a genuinely new order) from `on_hold -> processing` (a legacy order
    being triaged, legal per `ALLOWED_TRANSITIONS`). Threading the from-status through
    the effects table to separate them would change a signature every effect in the
    codebase shares, to fix a case that arises only during migration triage.

    The mitigation is in the template instead: the mail is headed "Payment confirmed",
    not "New order", and it states `placed_at`. An order placed in March that reaches
    processing in August announces itself honestly, which is all the distinction was
    ever going to buy.
    """
    _notify_safely("order.paid", order_pk)


def enqueue_staff_awaiting_transfer(order_pk: int) -> None:
    """Fires at placement, for bank transfer only — the same branch that mails the
    customer their account details.

    THIS IS THE ONE THAT BREAKS THE CIRCLE. Without it the first staff alert for a
    transfer order arrives when somebody confirms the payment, which requires somebody to
    already know the order exists. A transfer placed at 9am and unmatched by 9am next day
    is expired stock and a customer owed a refund, and nothing anywhere was going to
    mention it.
    """
    _notify_safely("order.awaiting_transfer", order_pk)


def _notify_safely(event: str, order_pk: int) -> None:
    """Build the context and hand it to `notify_staff`, swallowing anything that goes
    wrong.

    THIS GUARD IS THE POINT, and it covers the WHOLE call graph rather than just the
    enqueue. `on_commit` callbacks are not independent — one that raises abandons every
    callback registered after it (django/db/backends/base/base.py) and propagates into
    whatever committed the transaction. In checkout that is a 500 handed to a customer
    whose order was just successfully placed. Two database queries run in here
    (`_staff_order`, and `resolve_recipients` inside `notify_staff`), so "it cannot
    raise" was never true; it was only unlikely.

    A staff alert is worth strictly less than the order it describes. Losing one leaves a
    recoverable situation — the order is in the admin queue either way — so the honest
    behaviour is to log it and let everything else proceed.
    """
    try:
        notify_staff(event, _staff_context(_staff_order(order_pk)))
    except Exception:  # noqa: BLE001 — see docstring
        logger.exception("staff alert %s failed for order %s", event, order_pk)


def _staff_order(order_pk: int) -> Order:
    """`_send`'s loader with the extra joins the staff context needs. Separate because
    the customer path has no business fetching a country name or a GIG shipment it does
    not render, on every one of five emails."""
    return (
        Order.objects.select_related("currency", "country")
        # `payments` as well as `items`: the alert names the payment method, and without
        # the prefetch that is one extra query per alert inside `_notify_safely`'s
        # try/except — where a slow query is invisible rather than merely slow.
        .prefetch_related("items", "payments")
        .get(pk=order_pk)
    )
