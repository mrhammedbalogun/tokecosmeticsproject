"""`review_reason` accumulates rather than erasing.

Plan-09b adds a SECOND writer to `review_reason` inside one call stack:
confirm_manual_receipt's amount-delta branch runs after the verdict ladder has already
flagged. While _flag_review assigned, whichever wrote last erased the other — and staff
acted on the survivor. See test_a_second_flag_does_not_erase_the_first for the money.
"""
import pytest

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.orders.state import resolve_review
from apps.payments.services import _flag_review

pytestmark = pytest.mark.django_db


def _order(number="TC-100001"):
    ng = Country.objects.get(code="NG")
    return OrderFactory(number=number, country=ng, currency=ng.currency,
                        reservation_reference=number, grand_total="10000.00")


def test_a_second_flag_does_not_erase_the_first():
    # The money: a cancelled order the customer overpaid ₦12,000 on against ₦10,000.
    # The ladder says refund the WHOLE payment (goods never ship); the delta branch says
    # refund the ₦2,000 surplus. If the second erases the first, staff wire ₦2,000, resolve
    # the flag, and the customer is out ₦10,000 with no goods and nothing recording it.
    order = _order()
    _flag_review(order.pk, "payment 1 received on a cancelled order — refund it")
    _flag_review(order.pk, "overpaid by 2000 — refund the difference")

    order.refresh_from_db()
    assert "cancelled order" in order.review_reason
    assert "overpaid by 2000" in order.review_reason


def test_the_same_reason_twice_is_not_duplicated():
    # Retries and replays are normal here; the flag is a set of facts, not a log.
    order = _order()
    _flag_review(order.pk, "possible double payment")
    _flag_review(order.pk, "possible double payment")

    order.refresh_from_db()
    assert order.review_reason.count("possible double payment") == 1


def test_resolve_clears_every_accumulated_reason_in_one_act(django_user_model):
    # Plan-10's model is untouched: an explicit admin resolve is still the ONLY thing that
    # clears the flag, and it clears all of it.
    order = _order()
    _flag_review(order.pk, "first reason")
    _flag_review(order.pk, "second reason")

    staff = django_user_model.objects.create_user(email="staff@x.com", password="pw",
                                                  is_staff=True)
    resolve_review(order.pk, actor=staff, message="handled both")

    order.refresh_from_db()
    assert order.review_reason == ""
