"""Every aggregate the admin reports on. One module, on purpose.

── WHY ONE MODULE ──────────────────────────────────────────────────────────────────

Plan-20 ruling 1 declined the spec's nightly `DailySalesRollup`, and a deferral is only
honest if the seam it defers behind actually exists. This is that seam: views call these
functions and never write their own ORM aggregation, so a materialised table can later
slot in behind the same signatures without touching a single view.

**The trigger for revisiting is written down rather than left to feel:** ~100k orders, or
a report p95 past ~500ms on the VPS. And whoever builds it owns a FULL REBUILD path —
Plan-23 bulk-inserts 879 orders whose `placed_at` spans years, so any incremental rollup
built before that import is wrong the moment it runs.

── TWO DEFINITIONS THE WHOLE STAGE RESTS ON ────────────────────────────────────────

1. **Revenue is `Order.grand_total`, never `SUM(Payment.amount)`.** On an accepted
   discrepancy `confirm_manual_receipt` leaves `payment.amount` at the order total and
   records what actually arrived in `raw_response["manual_receipt"]`
   (`payments/services.py:420-428`). Summing payments would report the invoiced figure as
   though it were money in the bank. Reconciling invoiced-against-received is Plan-28's
   job, not this one's.

2. **Never mix currencies.** Every figure here is returned PER CURRENCY and the caller
   renders them side by side. A single "revenue" number that silently dropped GBP orders
   would be worse than showing two. Today production is NGN-only; Plan-23 changes that.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Count, DecimalField, F, Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce, TruncDay

from apps.checkout.models import CouponRedemption
from apps.orders.models import Order, OrderItem
from apps.payments.models import Refund

# Statuses in which money was actually taken. `pending_payment` and `expired` never had
# any; `cancelled` was released. `refunded` IS included — the money did arrive, and
# refunds are subtracted separately so that "gross, refunds, net" all reconcile rather
# than an order silently vanishing from history when it is refunded.
REVENUE_STATUSES: frozenset[str] = frozenset(
    {"processing", "shipped", "delivered", "completed", "on_hold", "refunded"}
)

_ZERO = Value(Decimal("0"), output_field=DecimalField(max_digits=14, decimal_places=2))


@dataclass(frozen=True)
class Range:
    """A closed-open date window plus an optional country. Closed-open so consecutive
    ranges cannot double-count the boundary day."""

    start: object
    end: object
    country: str = ""

    def filter(self, qs: QuerySet, field: str = "placed_at") -> QuerySet:
        qs = qs.filter(**{f"{field}__gte": self.start, f"{field}__lt": self.end})
        if self.country:
            qs = qs.filter(country_id=self.country)
        return qs

    @property
    def days(self) -> int:
        return max(1, (self.end - self.start).days)


def _orders(window: Range) -> QuerySet:
    return window.filter(Order.objects.filter(status__in=REVENUE_STATUSES))


def revenue_totals(window: Range) -> list[dict]:
    """Gross, refunds and net per currency, plus order count and AOV.

    Refunds are matched on the REFUND's own date, not the order's: a refund issued this
    month against last month's order belongs to this month's cash position, which is what
    somebody reading a monthly figure means.
    """
    gross = (
        _orders(window)
        .values("currency_id")
        .annotate(
            orders=Count("id"),
            gross=Coalesce(Sum("grand_total"), _ZERO),
        )
        .order_by("currency_id")
    )

    refunds_qs = Refund.objects.filter(status="succeeded")
    refunds_qs = refunds_qs.filter(
        created_at__gte=window.start, created_at__lt=window.end
    )
    if window.country:
        refunds_qs = refunds_qs.filter(payment__order__country_id=window.country)
    refunds = {
        row["payment__order__currency_id"]: row["total"]
        for row in refunds_qs.values("payment__order__currency_id").annotate(
            total=Coalesce(Sum("amount"), _ZERO)
        )
    }

    rows = []
    for row in gross:
        currency = row["currency_id"]
        refunded = refunds.pop(currency, Decimal("0"))
        orders = row["orders"] or 0
        rows.append({
            "currency": currency,
            "orders": orders,
            "gross": row["gross"],
            "refunds": refunded,
            "net": row["gross"] - refunded,
            # Average ORDER value, on gross: "what does a typical order come to" is a
            # question about orders placed, not about money kept.
            "aov": (row["gross"] / orders) if orders else Decimal("0"),
        })
    # A currency with refunds but no orders in the window is still real money moving.
    for currency, refunded in refunds.items():
        rows.append({
            "currency": currency, "orders": 0, "gross": Decimal("0"),
            "refunds": refunded, "net": -refunded, "aov": Decimal("0"),
        })
    return sorted(rows, key=lambda r: r["currency"])


def revenue_by_day(window: Range) -> list[dict]:
    """The revenue chart's series, per currency per day. Days with no orders are absent —
    the caller fills the gaps, because only it knows the axis it is drawing."""
    return list(
        _orders(window)
        .annotate(day=TruncDay("placed_at"))
        .values("day", "currency_id")
        .annotate(orders=Count("id"), gross=Coalesce(Sum("grand_total"), _ZERO))
        .order_by("day", "currency_id")
    )


def orders_by_status(window: Range) -> list[dict]:
    """EVERY status, not just the revenue ones — this answers "what is in the pipeline",
    which includes the orders that never paid.

    Deliberately a count list rather than a donut's slices: `needs_review` is a FLAG on an
    order, not a status (`orders/models.py`), so it can never be a slice here and a chart
    shaped like a pie invites exactly that mistake.
    """
    qs = window.filter(Order.objects.all())
    return list(qs.values("status").annotate(orders=Count("id")).order_by("-orders"))


def top_products(window: Range, limit: int = 10) -> list[dict]:
    """By revenue, per currency. Grouped on the SNAPSHOT name and sku rather than the
    variant FK, because `OrderItem.variant` is nullable (`SET_NULL`) and Plan-23 imports
    international items with no variant at all — grouping on the FK would drop them."""
    items = OrderItem.objects.filter(order__status__in=REVENUE_STATUSES)
    items = window.filter(items, field="order__placed_at")
    if window.country:
        items = items.filter(order__country_id=window.country)
    return list(
        items.values("sku", "product_name", "order__currency_id")
        .annotate(quantity=Coalesce(Sum("quantity"), 0), revenue=Coalesce(Sum("line_total"), _ZERO))
        .order_by("-revenue")[:limit]
    )


def sales_by_category(window: Range) -> list[dict]:
    """Revenue per category, WITH AN EXPLICIT UNATTRIBUTED ROW.

    Category lives behind `variant → product → categories`, and `OrderItem.variant` is
    nullable — Plan-23 imports international items without one. So some revenue cannot be
    attributed, and this returns it as a named row rather than dropping it. Without that,
    the category report's total would not equal the revenue report's and somebody would
    find the discrepancy during UAT with no explanation available.

    An item in two categories is counted in both, so category revenue SUMS ABOVE the
    total. That is a property of overlapping categories, not a bug, and the caller says so.
    """
    items = OrderItem.objects.filter(order__status__in=REVENUE_STATUSES)
    items = window.filter(items, field="order__placed_at")
    if window.country:
        items = items.filter(order__country_id=window.country)

    attributed = list(
        items.filter(variant__product__categories__isnull=False)
        .values(
            "order__currency_id",
            category=F("variant__product__categories__name"),
        )
        .annotate(revenue=Coalesce(Sum("line_total"), _ZERO))
        .order_by("-revenue")
    )
    unattributed = list(
        items.filter(
            Q(variant__isnull=True) | Q(variant__product__categories__isnull=True)
        )
        .values("order__currency_id")
        .annotate(revenue=Coalesce(Sum("line_total"), _ZERO))
        .order_by()
    )
    for row in unattributed:
        attributed.append({
            "category": None,  # rendered as "Unattributed"
            "order__currency_id": row["order__currency_id"],
            "revenue": row["revenue"],
        })
    return attributed


def top_customers(window: Range, limit: int = 10) -> list[dict]:
    """Per-customer orders and lifetime value IN THE WINDOW, per currency.

    ── THIS IS THE SHARED LAYER PLAN-18b CONSUMES ──────────────────────────────────

    18b's spec wants per-customer "orders count, lifetime value". If it computed those
    independently the two screens would disagree the first time either changed its status
    set. So 18b calls THIS, and `REVENUE_STATUSES` above is the single definition.

    PER CURRENCY, from day one: Plan-23 imports multi-currency history and this stage
    bans FX mixing, so a single-number LTV would be a signature 18b had to break.
    """
    return list(
        _orders(window)
        .values("email", "currency_id")
        .annotate(orders=Count("id"), lifetime_value=Coalesce(Sum("grand_total"), _ZERO))
        .order_by("-lifetime_value")[:limit]
    )


def customer_totals(user_id: int) -> list[dict]:
    """One customer's ALL-TIME orders and lifetime value, per currency.

    ── THE OTHER HALF OF THE SHARED LAYER (Plan-18b) ───────────────────────────────

    `top_customers` above answers "who spent most in this window"; this answers "what is
    this one person worth". Both sit on `REVENUE_STATUSES`, which is the point: a customer
    detail page whose lifetime value disagreed with the top-customers report would make
    both numbers untrustworthy, and neither screen would be obviously the wrong one.

    NO WINDOW. Lifetime means lifetime — a windowed LTV is a contradiction, and support
    asking "is this a good customer" wants the whole history.

    CLAIMED ORDERS ONLY (`user_id`), never a match on the email string. Guest orders
    sharing an address are surfaced separately and deliberately un-summed: attributing
    them here would put money against a person who has not proved the address is theirs,
    which is the same claim `apps/accounts/claims.py` refuses to make.
    """
    return list(
        Order.objects.filter(user_id=user_id, status__in=REVENUE_STATUSES)
        .values("currency_id")
        .annotate(orders=Count("id"), lifetime_value=Coalesce(Sum("grand_total"), _ZERO))
        .order_by("currency_id")
    )


def unclaimed_guest_orders(email: str) -> int:
    """Orders carrying this email that belong to NO account.

    Support's most common real question about a migrated customer — "why can't they see
    their old orders?" — and the answer is almost always that they have not verified the
    address yet. Reported as a count next to the lifetime value, never added into it.
    """
    email = (email or "").strip()
    if not email:
        return 0
    return Order.objects.filter(user__isnull=True, email__iexact=email).count()


def coupon_performance(window: Range) -> list[dict]:
    """Redemptions and the discount they gave away, per coupon.

    THE LEDGER HAS NO AMOUNT COLUMN (`checkout/models.py`), so the discount is reached
    through the soft reference `CouponRedemption.order_number → Order.number`. That join
    is why this is not simply a count.

    Plan-23 creates NO redemption rows for migrated coupon lines, so historical coupon
    performance legitimately begins at zero — the report says so rather than letting it
    read as "no coupon ever worked".
    """
    redemptions = CouponRedemption.objects.filter(
        created_at__gte=window.start, created_at__lt=window.end
    )
    orders = Order.objects.filter(status__in=REVENUE_STATUSES)
    if window.country:
        orders = orders.filter(country_id=window.country)
    discounts = {
        o["number"]: (o["discount_total"], o["currency_id"])
        for o in orders.values("number", "discount_total", "currency_id")
    }

    per_coupon: dict[tuple[str, str], dict] = {}
    for row in redemptions.select_related("coupon").values("coupon__code", "order_number"):
        discount, currency = discounts.get(row["order_number"], (Decimal("0"), ""))
        key = (row["coupon__code"], currency)
        entry = per_coupon.setdefault(
            key, {"code": row["coupon__code"], "currency": currency,
                  "redemptions": 0, "discount_total": Decimal("0")}
        )
        entry["redemptions"] += 1
        entry["discount_total"] += discount
    return sorted(per_coupon.values(), key=lambda r: -r["discount_total"])
