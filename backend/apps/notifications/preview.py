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
    "items": [
        {"name": "Sample Product", "variant": "100ml", "quantity": 2, "line_total": "₦20,000.00"},
        {"name": "Another Sample", "variant": "", "quantity": 1, "line_total": "₦5,000.00"},
    ],
    "item_count": 3,
    "grand_total": "₦25,000.00",
    "currency": "NGN",
    "country": "Nigeria",
    "delivery_option_name": "Sample delivery option",
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
    "delivery.gig_wallet_low": {
        "is_preview": True,
        # A string, matching what `monitor_gig_wallet` now sends — the real context
        # crosses Celery's JSON serializer and cannot carry a Decimal.
        "balance": "1000.00",
        "threshold": 50000,
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
