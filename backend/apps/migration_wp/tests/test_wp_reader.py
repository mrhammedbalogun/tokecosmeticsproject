"""Integration tests against a real WordPress database.

Skipped unless WP_DB_NAME is configured, so CI stays hermetic. Run manually on
the VPS after creating the wp_readonly grant.
"""
import pytest
from django.conf import settings

from apps.migration_wp import wp_reader

pytestmark = pytest.mark.skipif(
    not settings.WP_DB_NAME, reason="WP_DB_* not configured — integration test"
)


def test_fetch_products_returns_published_catalogue():
    with wp_reader.wp_connection() as conn:
        products = wp_reader.fetch_products(conn)
    published = [p for p in products if p["post_status"] == "publish"]
    assert len(published) >= 60, "expected ~69 published products"
    assert all(p["slug"] for p in published), "every product must have a slug"


def test_slugs_are_unique():
    with wp_reader.wp_connection() as conn:
        products = wp_reader.fetch_products(conn)
    slugs = [p["slug"] for p in products if p["post_status"] == "publish"]
    assert len(slugs) == len(set(slugs)), "duplicate slugs would break SEO preservation"


def test_acf_values_are_readable():
    with wp_reader.wp_connection() as conn:
        products = wp_reader.fetch_products(conn)
        ids = [p["ID"] for p in products[:5]]
        meta = wp_reader.fetch_meta(conn, ids)
    assert any(m.get("Benefits") for m in meta.values()), "ACF Benefits should be present"
