"""extract_wp_orders — file mode, the pre-HPOS fallback, and the extract/import seam."""

import json
import stat
from contextlib import contextmanager
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.migration_wp import wp_reader

HPOS_ROWS = [
    {"id": 21446, "status": "wc-completed", "currency": "USD", "type": "shop_order",
     "customer_id": 0, "billing_email": "a@example.com",
     "date_created_gmt": "2026-07-25 10:00:00", "date_updated_gmt": "2026-07-25 10:00:00",
     "payment_method": "stripe", "payment_method_title": "Card", "customer_note": "",
     "total_amount": "187.00", "tax_amount": "0.00", "date_paid_gmt": "2026-07-25 11:00:00",
     "date_completed_gmt": None, "shipping_total_amount": "0.00",
     "discount_total_amount": "0.00"},
]
# One genuinely missed by HPOS, and one that HPOS already has — the second must be dropped.
POST_ROWS = [
    {"id": 19039, "status": "wc-completed", "currency": "GBP", "type": "shop_order",
     "customer_id": 0, "billing_email": "old@example.com",
     "date_created_gmt": "2023-05-01 10:00:00", "date_updated_gmt": None,
     "payment_method": "rave", "payment_method_title": "Flutterwave", "customer_note": "",
     "total_amount": "40.00", "tax_amount": "0.00", "date_paid_gmt": "2023-05-01 11:00:00",
     "date_completed_gmt": None, "shipping_total_amount": "0.00",
     "discount_total_amount": "0.00"},
    dict(HPOS_ROWS[0]),
]


@pytest.fixture
def stub_wp(monkeypatch):
    @contextmanager
    def fake_connection():
        yield object()

    monkeypatch.setattr(wp_reader, "wp_connection", fake_connection)
    monkeypatch.setattr(wp_reader, "fetch_orders", lambda conn: [dict(r) for r in HPOS_ROWS])
    monkeypatch.setattr(
        wp_reader, "fetch_legacy_post_orders", lambda conn: [dict(r) for r in POST_ROWS]
    )
    monkeypatch.setattr(wp_reader, "fetch_order_addresses", lambda conn, ids: {})
    monkeypatch.setattr(wp_reader, "fetch_order_items", lambda conn, ids: {})


def test_THE_ARTIFACT_IS_0600(stub_wp, tmp_path):
    # Names, emails, phones and full postal addresses for 4,096 orders. Less immediately
    # dangerous than password hashes, more personal.
    out = tmp_path / "orders-legacy_ng.json"
    call_command("extract_wp_orders", "--store", "legacy_ng", "--out", str(out),
                 stdout=StringIO())
    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_the_pre_hpos_orders_are_EXCLUDED_by_default(stub_wp, tmp_path):
    out = tmp_path / "a.json"
    call_command("extract_wp_orders", "--store", "legacy_ng", "--out", str(out),
                 stdout=StringIO())
    ids = [o["id"] for o in json.loads(out.read_text())["orders"]]
    assert ids == [21446]


def test_THE_13_PRE_HPOS_ORDERS_ARE_FOUND_and_the_stale_copy_is_not(stub_wp, tmp_path):
    """Intl has 13 orders from 2023 that HPOS never backfilled — absent from wc_orders
    entirely, so the ordinary query cannot see them and they would be lost silently.

    The dedup matters as much as the fallback: an order present in BOTH tables must come
    from the HPOS row, because the posts copy is stale by definition."""
    out = tmp_path / "a.json"
    call_command("extract_wp_orders", "--store", "legacy_intl", "--out", str(out),
                 "--include-legacy-posts", stdout=StringIO())

    orders = json.loads(out.read_text())["orders"]
    ids = sorted(o["id"] for o in orders)
    assert ids == [19039, 21446]          # the missed one is added...
    assert len(orders) == 2               # ...and the duplicate is not
    assert sum(o["id"] == 21446 for o in orders) == 1


def test_the_operator_is_warned(stub_wp, tmp_path):
    out = StringIO()
    call_command("extract_wp_orders", "--store", "legacy_ng",
                 "--out", str(tmp_path / "a.json"), stdout=out)
    assert "delete it after import" in out.getvalue()


def test_an_unknown_store_is_refused_before_the_database_is_touched(tmp_path):
    with pytest.raises(CommandError):
        call_command("extract_wp_orders", "--store", "legacy_typo",
                     "--out", str(tmp_path / "a.json"))


def test_a_bad_out_path_fails_before_the_database_is_touched(tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x")
    with pytest.raises(CommandError, match="not usable"):
        call_command("extract_wp_orders", "--store", "legacy_ng",
                     "--out", str(blocker / "nested" / "a.json"))


def test_extract_and_import_agree_on_the_artifact_shape(stub_wp, tmp_path, db):
    """The seam most likely to rot: extract writes it, import reads it, nothing else
    checks they still agree."""
    from apps.core.models import Country, Currency
    from apps.orders.models import Order

    Currency.objects.get_or_create(code="USD", defaults={"name": "USD", "symbol": "$"})
    Country.objects.get_or_create(code="US", defaults={"name": "US", "currency_id": "USD"})

    out = tmp_path / "orders-legacy_intl.json"
    call_command("extract_wp_orders", "--store", "legacy_intl", "--out", str(out),
                 stdout=StringIO())
    call_command("import_orders", str(out), stdout=StringIO())

    order = Order.objects.get(number="INT-21446")
    assert order.status == "completed"
    assert order.currency_id == "USD"
