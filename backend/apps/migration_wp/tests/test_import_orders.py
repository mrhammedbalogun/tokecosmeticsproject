"""Plan-23 order import. Fixtures mirror the distribution measured on the live stores.

The load-bearing test in this file is `test_NO_UNPAID_ORDER_LANDS_IN_A_REVENUE_STATUS`.
Everything else is scaffolding around it.
"""

import json
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from apps.accounts.models import LegacyIdentity, LegacyStore
from apps.analytics.queries import REVENUE_STATUSES
from apps.core.models import Country, Currency
from apps.migration_wp.importers.orders import import_orders
from apps.orders.models import Order, OrderItem

pytestmark = pytest.mark.django_db

FIXTURES = Path(__file__).parent / "fixtures"


def artifact(store):
    return json.loads((FIXTURES / f"orders-{store}.json").read_text())


@pytest.fixture(autouse=True)
def markets(db):
    """The currencies and countries these orders arrive in. `Order.country`/`currency` are
    PROTECT FKs, so they have to exist before anything can land."""
    for code in ("NGN", "GBP", "USD", "CAD"):
        Currency.objects.get_or_create(code=code, defaults={"name": code, "symbol": code})
    for code, cur in (("NG", "NGN"), ("GB", "GBP"), ("US", "USD"), ("CA", "CAD")):
        Country.objects.get_or_create(
            code=code, defaults={"name": code, "currency_id": cur}
        )


def run(store, **kwargs):
    return import_orders(artifact(store), **kwargs)


# ── the money guard ──────────────────────────────────────────────────────────────────────


def test_NO_UNPAID_ORDER_LANDS_IN_A_REVENUE_STATUS():
    """The whole reason this stage was measured before it was written.

    `wc-on-hold` means "chose bank transfer, never paid" in WooCommerce and "money in
    hand" here. 2,277 orders, ₦34.2M on NG-current alone. If any unpaid order reaches a
    status `analytics.queries` counts, the dashboard reports revenue nobody received —
    silently, and in the flattering direction.
    """
    paid_by_key = {}
    for store in ("legacy_ng", "legacy_ng_old", "legacy_intl"):
        run(store)
        for row in artifact(store)["orders"]:
            paid_by_key[(store, str(row["id"]))] = bool(row.get("date_paid_gmt"))

    counted = 0
    for order in Order.objects.exclude(source="web"):
        if order.status not in REVENUE_STATUSES:
            continue
        counted += 1
        was_paid = paid_by_key[(order.source, order.legacy_number)]
        assert was_paid or order.review_reason, (
            f"{order.number} is counted as revenue ({order.status}) but WooCommerce "
            "records no payment date, and nothing flagged it for a human"
        )
    assert counted, "no order reached a revenue status — the guard proved nothing"


def test_the_unpaid_on_hold_orders_become_expired():
    run("legacy_ng")
    assert Order.objects.get(number="NG-16521").status == "expired"


def test_they_are_NOT_in_the_awaiting_payment_queue():
    # The decision: expired, not pending_payment. 2,277 rows would make the admin's
    # Awaiting-payment queue one nobody reads.
    run("legacy_ng")
    assert not Order.objects.filter(source="legacy_ng", status="pending_payment").exists()


# ── the status map, end to end ───────────────────────────────────────────────────────────


def test_paid_orders_keep_their_status():
    run("legacy_ng")
    assert Order.objects.get(number="NG-16520").status == "completed"
    assert Order.objects.get(number="NG-16000").status == "processing"


def test_A_TRASHED_ORDER_IS_NOT_RESURRECTED_but_a_paid_one_is_flagged():
    summary = run("legacy_ng")

    assert not Order.objects.filter(number="NG-11000").exists()   # trashed, unpaid
    assert summary["skipped_trashed"] == 1

    paid_trash = Order.objects.get(number="NG-11621")             # trashed, but £ moved
    assert paid_trash.status == "cancelled"
    assert "money moved" in paid_trash.review_reason


def test_cancelled_but_paid_is_flagged_for_a_human():
    run("legacy_ng")
    order = Order.objects.get(number="NG-15620")
    assert order.status == "cancelled"
    assert "refund" in order.review_reason.lower()


# ── numbering ────────────────────────────────────────────────────────────────────────────


def test_THE_COLLIDING_ID_IMPORTS_AS_TWO_DIFFERENT_ORDERS():
    """Order 21000 exists in BOTH the NG-old and intl stores — 26 real ones do. Without
    the store prefix the second import raises IntegrityError, or merges two customers'
    orders into one row."""
    run("legacy_ng_old")
    run("legacy_intl")

    assert Order.objects.filter(legacy_number="21000").count() == 2
    assert Order.objects.get(number="OLD-21000").source == "legacy_ng_old"
    assert Order.objects.get(number="INT-21000").source == "legacy_intl"
    assert Order.objects.get(number="INT-21000").currency_id == "GBP"


def test_the_legacy_number_is_what_the_customer_has():
    run("legacy_ng")
    assert Order.objects.get(number="NG-16521").legacy_number == "16521"


# ── linkage ──────────────────────────────────────────────────────────────────────────────


def test_A_REGISTERED_ORDER_LINKS_THROUGH_LegacyIdentity():
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(email="ada@example.com", password="x")
    LegacyIdentity.objects.create(user=user, store=LegacyStore.NG, wp_user_id=101)

    run("legacy_ng")

    assert Order.objects.get(number="NG-16520").user == user


def test_A_GUEST_ORDER_LANDS_WITH_user_None_AND_THE_REAL_EMAIL():
    # architecture.md requires exactly this, or claims.py can never attach them.
    run("legacy_ng")
    order = Order.objects.get(number="NG-16521")
    assert order.user is None
    assert order.email == "cust16521@example.com"


def test_A_REGISTERED_ORDER_IS_NEVER_MATCHED_TO_AN_ACCOUNT_BY_EMAIL():
    """The attack claims.py exists to refuse. An account holding the billing address —
    but with NO LegacyIdentity for that WordPress customer — must not inherit the order,
    because anyone can register any address they can receive mail at."""
    from django.contrib.auth import get_user_model

    impostor = get_user_model().objects.create_user(
        email="cust16520@example.com", password="x"
    )

    run("legacy_ng")

    order = Order.objects.get(number="NG-16520")
    assert order.user is None, "matched a registered order to an account by email"
    assert order.user != impostor
    assert order.email == "cust16520@example.com"  # still claimable, after verification


# ── money ────────────────────────────────────────────────────────────────────────────────


def test_THE_TOTALS_ADD_UP_AND_ARE_COPIED_NOT_RECOMPUTED():
    run("legacy_ng")
    order = Order.objects.get(number="NG-16521")

    assert order.grand_total == Decimal("10000.00")
    assert order.tax_total == Decimal("750.00")
    assert order.shipping_total == Decimal("1500.00")
    assert (
        order.subtotal + order.shipping_total + order.tax_total - order.discount_total
        == order.grand_total
    )


def test_line_items_are_kept_as_sold():
    run("legacy_ng")
    item = OrderItem.objects.get(order__number="NG-16521")
    assert item.product_name == "Shea Butter 250ml"
    assert item.quantity == 2
    assert item.line_total == Decimal("6250.00")
    assert item.unit_price == Decimal("3125.00")


def test_A_LINE_WITH_NO_PRODUCT_LINK_IS_KEPT_NOT_DROPPED():
    # 106 real line items have no _product_id. Dropping one changes the order total and
    # makes the migrated order disagree with the invoice the customer holds.
    summary = run("legacy_ng")
    assert summary["line_items_without_a_variant"] > 0
    assert OrderItem.objects.filter(order__number="NG-16519").exists()


def test_shipping_and_tax_lines_do_not_become_order_items():
    # They are already inside the order totals; adding them as items would double-count.
    run("legacy_ng")
    names = set(OrderItem.objects.values_list("product_name", flat=True))
    assert "Flat rate" not in names


# ── no payments, no stock ────────────────────────────────────────────────────────────────


def test_NO_PAYMENT_ROWS_ARE_CREATED():
    """`_refund_owned_by_the_ledger` depends on this: a legacy order has no captured
    payment here, which is what lets staff mark it refunded by hand. Inventing succeeded
    payments would make all 1,185 paid legacy orders refuse that transition."""
    run("legacy_ng")
    for order in Order.objects.filter(source="legacy_ng"):
        assert not order.payments.exists()


def test_how_they_paid_is_recorded_as_history():
    run("legacy_ng")
    event = Order.objects.get(number="NG-16000").events.get(type="migrated")
    assert "Debit/Credit Cards" in event.message
    assert "paystack" in event.message
    assert "No payment record was migrated" in event.message


def test_an_unpaid_order_says_so_in_its_event():
    run("legacy_ng")
    event = Order.objects.get(number="NG-16521").events.get(type="migrated")
    assert "never paid" in event.message


def test_STOCK_IS_NEVER_TOUCHED():
    from apps.inventory.models import StockMovement

    before = StockMovement.objects.count()
    run("legacy_ng")
    assert StockMovement.objects.count() == before


# ── idempotency ──────────────────────────────────────────────────────────────────────────


def test_running_twice_creates_nothing_the_second_time():
    first = run("legacy_ng")
    second = run("legacy_ng")

    assert first["created"] == 6  # 7 rows, 1 trashed-unpaid skipped
    assert second["created"] == 0
    assert second["updated"] == 6
    assert Order.objects.filter(source="legacy_ng").count() == 6


def test_a_rerun_does_not_duplicate_line_items():
    run("legacy_ng")
    before = OrderItem.objects.count()
    run("legacy_ng")
    assert OrderItem.objects.count() == before


def test_a_rerun_does_not_duplicate_the_migration_event():
    run("legacy_ng")
    run("legacy_ng")
    assert Order.objects.get(number="NG-16521").events.filter(type="migrated").count() == 1


def test_since_skips_older_orders():
    summary = run("legacy_ng", since="2026-07-18")
    assert summary["skipped_before_since"] > 0
    assert summary["created"] < 6


# ── the summary and the command ──────────────────────────────────────────────────────────


def test_the_summary_carries_no_pii():
    blob = json.dumps(run("legacy_ng"))
    for leak in ("cust16521@example.com", "Ada", "Okafor", "+2348012345678"):
        assert leak not in blob


def test_dry_run_writes_nothing():
    out = StringIO()
    call_command("import_orders", str(FIXTURES / "orders-legacy_ng.json"),
                 "--dry-run", stdout=out)
    assert "DRY RUN" in out.getvalue()
    assert Order.objects.count() == 0


def test_the_command_reports_reconciliation():
    out = StringIO()
    call_command("import_orders", str(FIXTURES / "orders-legacy_ng.json"), stdout=out)
    text = out.getvalue()
    assert "Reconciliation" in text
    assert "NGN: source 7 orders" in text
    # 1 trashed-unpaid row is deliberately not imported, and the report says so rather
    # than leaving a silent gap.
    assert "not imported" in text


def test_an_unknown_store_is_refused(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"version": 1, "store": "legacy_typo", "orders": []}))
    with pytest.raises(CommandError, match="legacy_typo"):
        call_command("import_orders", str(bad))


def test_THE_CHASE_CSV_IS_0600_AND_HOLDS_ONLY_RECENT_UNPAID_TRANSFERS(tmp_path):
    import stat

    csv_path = tmp_path / "chase.csv"
    call_command("import_orders", str(FIXTURES / "orders-legacy_ng.json"),
                 "--chase-csv", str(csv_path), stdout=StringIO())

    assert stat.S_IMODE(csv_path.stat().st_mode) == 0o600
    text = csv_path.read_text()
    assert "16521" in text            # the recent unpaid on-hold order
    assert "16520" not in text        # paid, so not chased
    assert "cust16521@example.com" in text


def test_the_intl_store_imports_every_currency():
    run("legacy_intl")
    assert set(
        Order.objects.filter(source="legacy_intl").values_list("currency_id", flat=True)
    ) == {"GBP", "USD", "CAD"}


def test_the_pre_hpos_order_imports_like_any_other():
    # The 13 intl orders HPOS never backfilled. They reach the importer through the same
    # code path, which is the point of translating them in the reader.
    run("legacy_intl")
    order = Order.objects.get(number="INT-19039")
    assert order.status == "completed"
    assert "Flutterwave" in order.events.get(type="migrated").message
