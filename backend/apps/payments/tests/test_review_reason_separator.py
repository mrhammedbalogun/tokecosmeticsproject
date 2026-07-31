"""`review_reason` must not accumulate the same sentence twice.

`_append_reason` deduped by splitting the stored text on `"; "` and testing membership.
That works until a reason CONTAINS the separator — and one of the five does:

    "possible double payment — order already processing; refund payment 7"

Stored, split, and looked for again, it comes back as two fragments and never matches
itself, so a second webhook for the same double payment appended it again. The flag an
operator reads when money has gone wrong would say the same thing twice, and there is no
upper bound on how often.

Found while building the Plan-18a orders list: the UI wanted to split the same string and
could not, for the same reason.

The separator is now a NEWLINE, which no reason contains, so splitting and dedupe are both
exact. Production had zero flagged orders when this changed, so nothing needed migrating.
"""
from decimal import Decimal
from itertools import count

import pytest

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.payments.services import _append_reason

pytestmark = pytest.mark.django_db

_numbers = count(400_001)

DOUBLE_PAYMENT = "possible double payment — order already processing; refund payment 7"
CANCELLED = "payment 3 received on a cancelled order — refund it"


def make_order():
    ng = Country.objects.get(code="NG")
    return OrderFactory(
        number=f"TC-{next(_numbers)}", country=ng, currency=ng.currency,
        status="processing", grand_total=Decimal("2000.00"),
    )


def test_a_reason_containing_the_separator_is_not_added_twice():
    """THE BUG. Two webhooks for one double payment used to leave the sentence twice."""
    order = make_order()

    assert _append_reason(order, DOUBLE_PAYMENT) is True
    assert _append_reason(order, DOUBLE_PAYMENT) is False

    assert order.review_reason.count("possible double payment") == 1


def test_an_ordinary_reason_is_still_deduped():
    order = make_order()

    assert _append_reason(order, CANCELLED) is True
    assert _append_reason(order, CANCELLED) is False

    assert order.review_reason == CANCELLED


def test_two_different_reasons_accumulate():
    order = make_order()

    _append_reason(order, CANCELLED)
    _append_reason(order, DOUBLE_PAYMENT)

    assert CANCELLED in order.review_reason
    assert DOUBLE_PAYMENT in order.review_reason


def test_accumulated_reasons_split_back_out_exactly():
    """The property the old separator could not offer, and what the admin UI needs to
    render them as separate items rather than one run-on block."""
    order = make_order()
    _append_reason(order, CANCELLED)
    _append_reason(order, DOUBLE_PAYMENT)

    assert order.review_reason.split("\n") == [CANCELLED, DOUBLE_PAYMENT]


def test_a_reason_survives_a_round_trip_with_its_semicolon_intact():
    order = make_order()

    _append_reason(order, DOUBLE_PAYMENT)

    assert order.review_reason.split("\n")[0] == DOUBLE_PAYMENT


def test_an_unflagged_order_takes_its_first_reason_cleanly():
    order = make_order()

    _append_reason(order, CANCELLED)

    assert order.review_reason == CANCELLED
    assert not order.review_reason.startswith("\n")


def test_legacy_semicolon_joined_text_is_left_alone():
    """Nothing in production carried a flag when the separator changed, but a row written
    by the old code must not be fragmented on read — it is treated as one reason, which is
    the safe direction: worst case an operator sees one long line."""
    order = make_order()
    order.review_reason = "old reason A; old reason B"

    added = _append_reason(order, CANCELLED)

    assert added is True
    assert order.review_reason.split("\n") == ["old reason A; old reason B", CANCELLED]


def test_the_caller_still_owns_the_save():
    """`_append_reason` mutates in memory and returns whether anything changed; callers
    holding the row lock must not re-open a transaction to write a note."""
    order = make_order()

    _append_reason(order, CANCELLED)
    order.refresh_from_db()

    assert order.review_reason == ""
