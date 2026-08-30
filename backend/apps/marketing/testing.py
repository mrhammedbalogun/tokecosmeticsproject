"""The canned event behind the admin's "Send test event" button.

Deliberately NOT built from a real order. A real order would put a real customer's
hashed email into whatever the platform's test console displays, and the button exists
to prove a credential works — which needs no customer at all.

The identifiers below are constants, not blanks, because a payload with an empty
`user_data` is refused by Meta and Snapchat for having nothing to match on, and a
refusal for THAT reason would look exactly like a bad token. The email is on
`example.com`, which RFC 2606 reserves precisely so it can never reach a person.
"""
from __future__ import annotations

import time
from decimal import Decimal

from apps.marketing.payloads import PURCHASE, ContentItem, ConversionPayload, UserSignals

TEST_ORDER_NUMBER = "TC-TEST-EVENT"


def test_payload() -> ConversionPayload:
    """A £0.00-value purchase with a fixed event id.

    The value is ZERO on purpose: if the channel has no `test_event_code` set, this
    lands in the live dataset as a real purchase, and a zero-value one distorts no
    reporting and trains no optimisation. A £1 test event in a live dataset is a lie the
    ad platform will act on.

    The event id is FIXED rather than random, so pressing the button ten times produces
    one event in the platform's console rather than ten — the same deduplication that
    protects a retried purchase.
    """
    return ConversionPayload(
        event_name=PURCHASE,
        event_id=TEST_ORDER_NUMBER,
        event_time=int(time.time()),
        source_url="https://tokecosmetics.com/",
        currency="NGN",
        value=Decimal("0"),
        order_number=TEST_ORDER_NUMBER,
        contents=(
            ContentItem(content_id="TEST-SKU", quantity=1, item_price=Decimal("0"),
                        name="Conversions API test"),
        ),
        user=UserSignals(
            email="conversions-api-test@example.com",
            phone="+2348000000000",
            first_name="Test",
            last_name="Event",
            country="NG",
            client_ip="127.0.0.1",
            client_user_agent="TokeCosmetics/1.0 (conversions API test)",
        ),
    )
