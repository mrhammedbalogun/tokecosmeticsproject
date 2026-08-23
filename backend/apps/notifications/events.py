"""The catalogue of things staff can be emailed about.

THE REGISTRY LIVES IN CODE, NOT THE DATABASE, and that is the load-bearing decision in
this module. An event exists only if some line of production code fires it; a row in an
`events` table that no code sends is a promise the admin screen would happily display and
nothing would ever keep. Keeping the registry a Python constant means "what can I
subscribe to?" and "what does the code actually send?" cannot drift apart.

The DATABASE stores subscriptions only (`NotificationRecipient`), keyed by these codes.
That is the half that genuinely varies per shop and per week.

── ADDING AN EVENT ─────────────────────────────────────────────────────────────────
1. Add an entry below, naming its template.
2. Add `email/<template>.subject.txt`, `.txt` and `.html` under `templates/email/`.
3. Call `notify_staff("<code>", context)` from wherever the thing happens.
Nothing else. The admin screen renders whatever is in this tuple, so a new event needs no
frontend change — which is the point of the owner's "and future email notifications" ask.

`template` is spelled out rather than derived from the code (`order.paid` ->
`staff_order_paid`) because two of the four events below predate this module and already
own template files under names that describe them well. A derived name would have meant
renaming live templates to satisfy a convention. The drift a spelled-out name invites is
closed by `tests/test_events.py::test_every_event_template_renders`, which renders all
three files for every registered event against a sample context — a missing or misnamed
template is a test failure, not a 500 at 2am.

── WHY `order.paid` AND `order.awaiting_transfer` ARE SEPARATE ─────────────────────
They have different audiences and different urgency, and one combined "new order" event
would force whoever packs boxes to also read every unpaid bank-transfer order that will
never be paid.

* `order.awaiting_transfer` fires when a customer completes checkout choosing BANK
  TRANSFER — money is expected but has not arrived. Its reader is whoever watches the
  bank account, because an unmatched transfer expires in 24h (`apps/orders/tasks.py`) and
  takes a paying customer's order with it. Instant gateways deliberately do not fire it:
  that customer is mid-redirect and either pays in seconds or never existed.
  NOT NAMED `order.placed`, though it is the placement hook: it fires from ONE branch of
  checkout (`InitiateResult.action == "bank_details"`), so a card order is equally
  "placed" and would never trigger it. An event whose label lies about when it fires gets
  mis-subscribed by whoever reads this screen.
* `order.paid` fires when payment is confirmed and stock is committed — the order is real
  and someone must pack it. This is what most shops mean by "new order alert".

An order paid by card produces exactly ONE staff mail; an order paid by transfer produces
up to two, at the two moments a human is actually needed.

── THE TWO ALERTS THAT WERE MAILING NOBODY ─────────────────────────────────────────
`inventory.low_stock` and `delivery.gig_wallet_low` existed before this module and were
addressed to `settings.DEFAULT_FROM_EMAIL` — `hello@mg.tokecosmetics.com`, the Resend
SENDING subdomain, which has no inbox. Every one of those alerts has been delivered to
nobody since the day it shipped, and probably bouncing against our own sending
reputation. Moving them onto this registry is what makes the screen worth having: the
same list that decides who hears about an order decides who hears that stock ran out.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationEvent:
    code: str
    label: str
    #: Shown under the label on the admin screen. Written for the person deciding whether
    #: to put an address on the list, so it says WHEN it fires and WHO wants it.
    description: str
    #: Template stem under `templates/email/`. See the module docstring.
    template: str


EVENTS: tuple[NotificationEvent, ...] = (
    NotificationEvent(
        code="order.paid",
        label="New paid order",
        description=(
            "A customer's payment has been confirmed and the order is ready to pack. "
            "This is the one to choose if you only want one."
        ),
        template="staff_order_paid",
    ),
    NotificationEvent(
        code="order.awaiting_transfer",
        label="Bank transfer awaiting payment",
        description=(
            "A customer chose bank transfer at checkout and has been given the account "
            "details. Nobody has paid yet — the order expires in 24 hours if the "
            "transfer is not matched. For whoever watches the bank account."
        ),
        template="staff_order_awaiting_transfer",
    ),
    NotificationEvent(
        code="inventory.low_stock",
        label="Low stock",
        description=(
            "A digest of every variant at or below its reorder threshold, sent when the "
            "list changes rather than on a timer. For whoever reorders."
        ),
        template="low_stock_digest",
    ),
    NotificationEvent(
        code="delivery.gig_wallet_low",
        label="GIG wallet running low",
        description=(
            "The prepaid GIG delivery wallet has crossed below its threshold. An empty "
            "wallet stops waybills being created, which halts the packing bench without "
            "affecting checkout — so nobody finds out until someone is standing at it."
        ),
        template="gig_wallet_low",
    ),
    NotificationEvent(
        code="delivery.aaj_attention",
        label="AAJ shipment needs attention",
        description=(
            "An AAJ Express parcel was returned, voided at AAJ's end, flagged with an "
            "exception, or reweighed (AAJ may bill the difference) — and once a day, if "
            "AAJ's state list drifts from ours. For whoever runs the packing bench."
        ),
        template="aaj_attention",
    ),
)

EVENTS_BY_CODE: dict[str, NotificationEvent] = {event.code: event for event in EVENTS}


def is_event(code: str) -> bool:
    return code in EVENTS_BY_CODE
