"""Sample contexts, one per registered event.

WHAT THESE ARE FOR. The "send test" button on the Email Notifications screen, and the
test that renders every registered template (`tests/test_events.py`). Both need a context
that exercises the template without needing a real order, a real low-stock situation or a
real GIG outage to exist first — which is the whole difficulty with verifying an alert
that only fires when something has gone wrong.

FAKE DATA IS OBVIOUSLY FAKE. Order number `TC-000000`, a made-up product, a total nobody
would mistake for a sale. A test send lands in an inbox next to real alerts, and a
plausible-looking sample is one somebody eventually acts on — packs a box for, or chases
a customer about. The `is_preview` flag lets templates say so out loud; the shared staff
partial renders a banner on it.

KEPT IN STEP BY A TEST, not by discipline. `test_every_event_has_a_preview_context`
asserts this dict's keys are exactly the registry's codes, so an event added without a
sample fails the suite rather than 500ing the day somebody presses Send test.
"""
from __future__ import annotations

_ORDER = {
    "is_preview": True,
    "number": "TC-000000",
    "placed_at": "01 Jan 2026, 09:00",
    "expires_at": "02 Jan 2026, 09:00",
    "admin_url": "",  # filled per-call, see below
    # BOTH SAMPLE LINES HAVE NO PICTURE, on purpose. An earlier draft pointed one at a
    # real production CDN filename; deleting or re-shooting that product would have turned
    # every future test send into a broken-image icon, which is a worse first impression
    # than a blank cell. The empty case is also the one worth exercising — it is what a
    # line whose product has been deleted renders as, and the layout has to hold without
    # the column.
    "items": [
        {"name": "Sample Product", "variant": "100ml", "quantity": 2,
         "line_total": "₦20,000.00", "image": "", "image_alt": "Sample Product"},
        {"name": "Another Sample", "variant": "", "quantity": 1,
         "line_total": "₦5,000.00", "image": "", "image_alt": "Another Sample"},
    ],
    "item_count": 3,
    # Exercised so the "send test" button renders the referral row rather than silently
    # skipping it — the whole point of a preview is to see the branch that only fires on
    # some real orders.
    "referral_discount_total": "₦1,250.00",
    "referral_discount_percent": "5",
        "combo_discount_total": "₦2,000.00",
    "grand_total": "₦25,000.00",
    "currency": "NGN",
    "country": "Nigeria",
    "delivery_option_name": "Sample delivery option",
    # Obviously-fake, like everything else here: a test send lands next to real alerts and
    # a plausible name is one somebody eventually packs a box for.
    "customer_name": "Sample Customer",
    "payment_method": "Bank transfer",
    "destination": "Ikeja, Lagos, Nigeria",
    "is_pickup": False,
    "customer_note": "This is a test — no such order exists.",
    "review_reason": "",
}

_PREVIEWS: dict[str, dict] = {
    "order.paid": _ORDER,
    "order.awaiting_transfer": _ORDER,
    "inventory.low_stock": {
        "is_preview": True,
        "rows": [
            {"sku": "SAMPLE-001", "warehouse": "Sample warehouse", "available": 2},
            {"sku": "SAMPLE-002", "warehouse": "Sample warehouse", "available": 0},
        ],
        "newly_low": [
            {"sku": "SAMPLE-002", "warehouse": "Sample warehouse", "available": 0},
        ],
        "is_first": False,
    },
    "delivery.aaj_attention": {
        "is_preview": True,
        "order_number": "TC-10234",
        "tracking_id": "6961577F",
        "status_label": "Returned",
        "reason": "returned to sender",
        "description": "Shipment has been returned",
    },
    "delivery.gig_wallet_low": {
        "is_preview": True,
        # A string, matching what `monitor_gig_wallet` now sends — the real context
        # crosses Celery's JSON serializer and cannot carry a Decimal.
        "balance": "1,000.00",
        "threshold": "50,000",
    },
}


def preview_context(event: str) -> dict:
    """A JSON-safe sample context for `event`, or `{}` for an unregistered one.

    Returns a DEEP copy. The dicts above are module-level constants shared between calls
    (`order.paid` and `order.awaiting_transfer` are literally the same object), so a
    caller that mutated one — adding a real order number to a preview, say — would poison
    every later test send in the process. A shallow `dict()` would leave the nested
    `items`/`rows` lists shared and the protection only half-true.
    """
    import copy

    from django.conf import settings

    context = copy.deepcopy(_PREVIEWS.get(event, {}))
    if "admin_url" in context:
        context["admin_url"] = f"{settings.ADMIN_URL}/orders"
    return context
