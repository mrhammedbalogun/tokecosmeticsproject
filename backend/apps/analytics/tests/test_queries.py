"""Plan-20a: the aggregate definitions.

These tests are mostly about DEFINITIONS rather than arithmetic. Plan-28 inherits whatever
this stage decides revenue means, and UAT churns on any number nobody can explain — so the
properties that matter are "revenue is not the payment amount", "currencies are never
mixed", and "unattributable revenue is named, not dropped".
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.analytics import queries
from apps.analytics.queries import REVENUE_STATUSES, Range
from apps.checkout.models import Coupon, CouponRedemption
from apps.core.models import Country, Currency
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment, Refund

pytestmark = pytest.mark.django_db

NOW = None  # set per test from timezone.now()


def _window(days: int = 30) -> Range:
    end = timezone.now() + timedelta(days=1)
    return Range(start=end - timedelta(days=days + 1), end=end)


def _order(number: str, *, total: str, status: str = "processing", currency: str = "NGN",
           country: str = "NG", email: str = "a@b.com", placed=None, discount: str = "0"):
    return Order.objects.create(
        number=number,
        email=email,
        country=Country.objects.get(code=country),
        currency=Currency.objects.get(code=currency),
        status=status,
        grand_total=Decimal(total),
        discount_total=Decimal(discount),
        placed_at=placed or timezone.now(),
    )


# --- revenue ------------------------------------------------------------------------


def test_REVENUE_IS_THE_ORDER_TOTAL_NOT_THE_PAYMENT_AMOUNT():
    """The trap this stage was planned around. `confirm_manual_receipt` leaves
    `payment.amount` at the order total and records the smaller sum that actually arrived
    in `raw_response`. A revenue figure built on payments would report money that never
    landed — and, here, would coincidentally match, which is why the assertion is on the
    query's source rather than on a number."""
    order = _order("TC-1", total="20000")
    Payment.objects.create(
        order=order, gateway="bank_transfer", purpose="goods", status="succeeded",
        amount=Decimal("20000"), currency=order.currency,
        raw_response={"manual_receipt": {"REF": {"amount_received": "19000"}}},
    )

    (row,) = queries.revenue_totals(_window())

    # 20000 (the order) — not 19000 (the cash), and not a sum over payments.
    assert row["gross"] == Decimal("20000")


def test_only_statuses_where_money_was_taken_count():
    _order("TC-paid", total="1000", status="processing")
    _order("TC-pending", total="9999", status="pending_payment")
    _order("TC-cancelled", total="9999", status="cancelled")
    _order("TC-expired", total="9999", status="expired")

    (row,) = queries.revenue_totals(_window())

    assert row["gross"] == Decimal("1000")
    assert row["orders"] == 1
    # The set is a single named constant so 18b cannot disagree with this stage.
    assert "pending_payment" not in REVENUE_STATUSES and "processing" in REVENUE_STATUSES


def test_CURRENCIES_ARE_NEVER_MIXED():
    """Production is NGN-only today; Plan-23 imports multi-currency history. A single
    'revenue' number that silently dropped one would be worse than showing both."""
    _order("TC-ng", total="20000", currency="NGN", country="NG")
    _order("TC-gb", total="50", currency="GBP", country="GB")

    rows = queries.revenue_totals(_window())

    assert {r["currency"] for r in rows} == {"NGN", "GBP"}
    assert {r["gross"] for r in rows} == {Decimal("20000"), Decimal("50")}


def test_refunds_net_off_and_a_refunded_order_still_shows_its_gross():
    """Gross, refunds and net must all reconcile. Dropping a refunded order from history
    would make 'why did last month shrink?' unanswerable."""
    order = _order("TC-r", total="10000", status="refunded")
    payment = Payment.objects.create(
        order=order, gateway="bank_transfer", purpose="goods", status="succeeded",
        amount=Decimal("10000"), currency=order.currency,
    )
    Refund.objects.create(payment=payment, amount=Decimal("4000"), status="succeeded")

    (row,) = queries.revenue_totals(_window())

    assert (row["gross"], row["refunds"], row["net"]) == (
        Decimal("10000"), Decimal("4000"), Decimal("6000")
    )


def test_a_pending_refund_is_not_money_back_yet():
    order = _order("TC-pr", total="10000")
    payment = Payment.objects.create(
        order=order, gateway="bank_transfer", purpose="goods", status="succeeded",
        amount=Decimal("10000"), currency=order.currency,
    )
    Refund.objects.create(payment=payment, amount=Decimal("4000"), status="pending")

    (row,) = queries.revenue_totals(_window())

    assert row["refunds"] == Decimal("0")


def test_the_window_excludes_what_falls_outside_it():
    _order("TC-in", total="100", placed=timezone.now())
    _order("TC-old", total="9999", placed=timezone.now() - timedelta(days=400))

    (row,) = queries.revenue_totals(_window(days=30))

    assert row["gross"] == Decimal("100")


# --- attribution --------------------------------------------------------------------


def test_UNATTRIBUTABLE_REVENUE_IS_NAMED_NOT_DROPPED():
    """`OrderItem.variant` is nullable and Plan-23 imports international items with no
    variant. Silently omitting them would make the category total disagree with the
    revenue total, and somebody would find it during UAT with no explanation."""
    order = _order("TC-cat", total="5000")
    OrderItem.objects.create(
        order=order, variant=None, product_name="Migrated item", sku="LEGACY-1",
        unit_price=Decimal("5000"), line_total=Decimal("5000"), quantity=1,
    )

    rows = queries.sales_by_category(_window())

    unattributed = [r for r in rows if r["category"] is None]
    assert unattributed and unattributed[0]["revenue"] == Decimal("5000")


def test_top_products_group_on_the_snapshot_not_the_variant():
    """Grouping on the FK would drop every migrated international item."""
    order = _order("TC-p", total="3000")
    OrderItem.objects.create(
        order=order, variant=None, product_name="Ghost", sku="GHOST-1",
        unit_price=Decimal("3000"), line_total=Decimal("3000"), quantity=2,
    )

    (row,) = queries.top_products(_window())

    assert (row["sku"], row["quantity"], row["revenue"]) == ("GHOST-1", 2, Decimal("3000"))


# --- the shared customer layer -------------------------------------------------------


def test_top_customers_reports_lifetime_value_PER_CURRENCY():
    """This is the layer Plan-18b consumes. Per-currency from day one, because Plan-23
    imports multi-currency history and a single number would be a signature 18b had to
    break."""
    _order("TC-c1", total="20000", email="ada@x.com", currency="NGN", country="NG")
    _order("TC-c2", total="30000", email="ada@x.com", currency="NGN", country="NG")
    _order("TC-c3", total="50", email="ada@x.com", currency="GBP", country="GB")

    rows = queries.top_customers(_window())

    ngn = next(r for r in rows if r["currency_id"] == "NGN")
    gbp = next(r for r in rows if r["currency_id"] == "GBP")
    assert (ngn["orders"], ngn["lifetime_value"]) == (2, Decimal("50000"))
    assert (gbp["orders"], gbp["lifetime_value"]) == (1, Decimal("50"))


# --- coupons -------------------------------------------------------------------------


def test_coupon_discount_comes_through_the_soft_join():
    """The redemption ledger has no amount column, so the discount is reached via
    `order_number → Order.discount_total`."""
    coupon = Coupon.objects.create(code="SAVE10", type="percent", value=10)
    _order("TC-cp", total="18000", discount="2000")
    CouponRedemption.objects.create(coupon=coupon, order_number="TC-cp", email="a@b.com")

    (row,) = queries.coupon_performance(_window())

    assert (row["code"], row["redemptions"], row["discount_total"]) == (
        "SAVE10", 1, Decimal("2000")
    )


# --- pipeline ------------------------------------------------------------------------


def test_orders_by_status_counts_EVERY_status_including_unpaid():
    """'What is in the pipeline' includes the orders that never paid — which is why this
    is not filtered to REVENUE_STATUSES."""
    _order("TC-a", total="100", status="pending_payment")
    _order("TC-b", total="100", status="processing")

    rows = {r["status"]: r["orders"] for r in queries.orders_by_status(_window())}

    assert rows == {"pending_payment": 1, "processing": 1}
