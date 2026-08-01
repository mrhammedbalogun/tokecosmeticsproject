"""Tests for the read-only SQL layer over the live WooCommerce database.

Two kinds of tests live here:
- A hermetic unit test for fetch_meta's key-filtering (fake connection, no
  MariaDB needed) that always runs.
- Integration tests that need a real WordPress database, individually skipped
  unless WP_DB_NAME is configured, so CI stays hermetic. Run manually on the
  VPS after creating the wp_readonly grant.
"""
import logging

import pytest
from django.conf import settings

from apps.migration_wp import wp_reader

_needs_live_db = pytest.mark.skipif(
    not settings.WP_DB_NAME, reason="WP_DB_* not configured — integration test"
)


class _FakeCursor:
    """Just enough of DictCursor's interface for fetch_meta to run against."""

    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)

    def close(self):
        pass


def test_fetch_meta_drops_noise_keeps_allowlist_and_logs_dropped(caplog):
    """A known-noise key is dropped; every allowlisted key/prefix survives."""
    rows = [
        {"post_id": 1, "meta_key": "_sku", "meta_value": "TOKE-1"},
        {"post_id": 1, "meta_key": "_regular_price", "meta_value": "12.00"},
        {"post_id": 1, "meta_key": "_sale_price", "meta_value": "10.00"},
        {"post_id": 1, "meta_key": "_sale_price_dates_from", "meta_value": "1690000000"},
        {"post_id": 1, "meta_key": "_sale_price_dates_to", "meta_value": "1690999999"},
        {"post_id": 1, "meta_key": "_stock", "meta_value": "5"},
        {"post_id": 1, "meta_key": "_stock_status", "meta_value": "instock"},
        {"post_id": 1, "meta_key": "_manage_stock", "meta_value": "yes"},
        {"post_id": 1, "meta_key": "_weight", "meta_value": "0.3"},
        {"post_id": 1, "meta_key": "_thumbnail_id", "meta_value": "9001"},
        {"post_id": 1, "meta_key": "_product_image_gallery", "meta_value": "9002,9003"},
        {"post_id": 1, "meta_key": "_product_attributes", "meta_value": "a:1:{}"},
        {"post_id": 1, "meta_key": "Benefits", "meta_value": "Softens skin.  Reduces itching."},
        {"post_id": 1, "meta_key": "product_main_usp", "meta_value": "Daily hydration"},
        {"post_id": 1, "meta_key": "attribute_pa_product-size", "meta_value": "50ml"},
        {"post_id": 1, "meta_key": "product_usp_1", "meta_value": "Fast absorbing"},
        {"post_id": 1, "meta_key": "Testimonial_1_Review_Text", "meta_value": "Great!"},
        {"post_id": 1, "meta_key": "Small_Image_1", "meta_value": "9004"},
        {"post_id": 1, "meta_key": "Medium_Image_1", "meta_value": "9005"},
        # Real-world noise (per Plan-21 coordinator review) that must be dropped.
        {"post_id": 1, "meta_key": "_edit_lock", "meta_value": "1753000000:1"},
        {"post_id": 1, "meta_key": "_edit_last", "meta_value": "1"},
        {"post_id": 1, "meta_key": "total_sales", "meta_value": "42"},
        {"post_id": 1, "meta_key": "_elementor_page_assets", "meta_value": "a:0:{}"},
        {"post_id": 1, "meta_key": "rvx_sync_new_status", "meta_value": "0"},
        {"post_id": 1, "meta_key": "_Benefits", "meta_value": "field_68e62397bfcc9"},  # ACF field-key twin
    ]
    conn = _FakeConn(rows)

    with caplog.at_level(logging.INFO, logger="apps.migration_wp.wp_reader"):
        meta = wp_reader.fetch_meta(conn, [1])

    kept = meta[1]

    for key in wp_reader._META_KEYS_EXACT:
        assert key in kept, f"allowlisted exact key {key!r} was dropped"

    for prefixed_sample in (
        "attribute_pa_product-size",
        "product_usp_1",
        "Testimonial_1_Review_Text",
        "Small_Image_1",
        "Medium_Image_1",
    ):
        assert prefixed_sample in kept, f"allowlisted-prefix key {prefixed_sample!r} was dropped"

    for noise_key in (
        "_edit_lock",
        "_edit_last",
        "total_sales",
        "_elementor_page_assets",
        "rvx_sync_new_status",
        "_Benefits",
    ):
        assert noise_key not in kept, f"noise key {noise_key!r} should have been dropped"

    dropped_log = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("Dropped"))
    assert "_edit_lock" in dropped_log
    assert "total_sales" in dropped_log
    assert "_Benefits" in dropped_log


class _RecordingConnect:
    """Stands in for pymysql.connect and remembers how it was called."""

    def __init__(self):
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return _FakeConn([])


def test_wp_connection_dials_tcp_for_a_hostname(monkeypatch, settings):
    settings.WP_DB_NAME = "tokecosm_wp481"
    settings.WP_DB_HOST = "172.17.0.1"
    settings.WP_DB_PORT = 3306
    connect = _RecordingConnect()
    monkeypatch.setattr(wp_reader.pymysql, "connect", connect)

    with wp_reader.wp_connection():
        pass

    assert connect.kwargs["host"] == "172.17.0.1"
    assert connect.kwargs["port"] == 3306
    assert "unix_socket" not in connect.kwargs


def test_wp_connection_uses_a_unix_socket_when_the_host_is_a_path(monkeypatch, settings):
    """MariaDB on the VPS binds 127.0.0.1 only, so the container dials the
    bind-mounted socket instead. pymysql ignores host/port in socket mode, so
    passing them alongside would be a lie about where the data came from."""
    settings.WP_DB_NAME = "tokecosm_wp481"
    settings.WP_DB_HOST = "/run/wp-mysql/mysql.sock"
    connect = _RecordingConnect()
    monkeypatch.setattr(wp_reader.pymysql, "connect", connect)

    with wp_reader.wp_connection():
        pass

    assert connect.kwargs["unix_socket"] == "/run/wp-mysql/mysql.sock"
    assert "host" not in connect.kwargs
    assert "port" not in connect.kwargs


@_needs_live_db
def test_fetch_products_returns_published_catalogue():
    with wp_reader.wp_connection() as conn:
        products = wp_reader.fetch_products(conn)
    published = [p for p in products if p["post_status"] == "publish"]
    assert len(published) >= 60, "expected ~69 published products"
    assert all(p["slug"] for p in published), "every product must have a slug"


@_needs_live_db
def test_slugs_are_unique():
    with wp_reader.wp_connection() as conn:
        products = wp_reader.fetch_products(conn)
    slugs = [p["slug"] for p in products if p["post_status"] == "publish"]
    assert len(slugs) == len(set(slugs)), "duplicate slugs would break SEO preservation"


@_needs_live_db
def test_acf_values_are_readable():
    with wp_reader.wp_connection() as conn:
        products = wp_reader.fetch_products(conn)
        ids = [p["ID"] for p in products[:5]]
        meta = wp_reader.fetch_meta(conn, ids)
    assert any(m.get("Benefits") for m in meta.values()), "ACF Benefits should be present"


# ── customers (Plan-22) ──────────────────────────────────────────────────────────────────


class _RecordingCursor(_FakeCursor):
    """Captures the SQL so the filter itself can be asserted, not just its output."""

    def __init__(self, rows, sink):
        super().__init__(rows)
        self._sink = sink

    def execute(self, sql, params=None):
        self._sink.append(sql)


class _RecordingConn(_FakeConn):
    def __init__(self, rows):
        super().__init__(rows)
        self.sql = []

    def cursor(self):
        return _RecordingCursor(self._rows, self.sql)


def test_FETCH_CUSTOMERS_REQUIRES_AN_ORDER_which_is_what_excludes_the_signup_flood():
    """These stores are under an automated signup flood — the intl store went from 51
    users on 14 July to 3,284 on 1 August, none of whom ever ordered, and it was still
    climbing while this was written. `EXISTS (an order)` is the only thing standing
    between that and several thousand imported spam accounts, so the predicate is
    asserted here rather than trusted to survive a future edit."""
    conn = _RecordingConn([])
    wp_reader.fetch_customers(conn)

    sql = " ".join(conn.sql[0].split())
    assert "EXISTS" in sql
    assert "wc_orders" in sql
    assert "customer_id > 0" in sql  # guests have no user row to migrate


def test_SESSION_TOKENS_NEVER_LEAVE_THE_SERVER():
    """wp_usermeta holds `session_tokens` — LIVE session material for the running store.
    An artifact containing it would be a file that grants login to the WordPress site it
    was extracted from. The allow-list is the control; this is the test that it holds."""
    rows = [
        {"user_id": 1, "meta_key": "first_name", "meta_value": "Ada"},
        {"user_id": 1, "meta_key": "billing_phone", "meta_value": "+2348012345678"},
        {"user_id": 1, "meta_key": "session_tokens", "meta_value": "a:1:{s:64:\"deadbeef\";}"},
        {"user_id": 1, "meta_key": "wp_capabilities", "meta_value": "a:1:{s:8:\"customer\";b:1;}"},
        {"user_id": 1, "meta_key": "_woocommerce_persistent_cart", "meta_value": "{}"},
    ]
    out = wp_reader.fetch_user_meta(_FakeConn(rows), [1])

    assert out[1] == {"first_name": "Ada", "billing_phone": "+2348012345678"}
    assert "session_tokens" not in out[1]
    assert "wp_capabilities" not in out[1]


def test_the_usermeta_allowlist_has_no_prefix_rules():
    # fetch_meta (catalogue) matches on prefixes; this one must not. A prefix rule here is
    # how `session_tokens` or a future `_secret_*` key gets in by accident.
    assert all(not k.endswith("_") for k in wp_reader._USER_META_KEYS)
    for key in wp_reader._USER_META_KEYS:
        assert key in {"first_name", "last_name", "billing_first_name",
                       "billing_last_name", "billing_phone"}


def test_fetch_user_meta_logs_what_it_dropped(caplog):
    rows = [{"user_id": 1, "meta_key": "session_tokens", "meta_value": "x"}]
    with caplog.at_level(logging.INFO, logger="apps.migration_wp.wp_reader"):
        wp_reader.fetch_user_meta(_FakeConn(rows), [1])
    assert "session_tokens" in caplog.text


def test_fetch_user_meta_of_nothing_queries_nothing():
    conn = _RecordingConn([])
    assert wp_reader.fetch_user_meta(conn, []) == {}
    assert conn.sql == []
