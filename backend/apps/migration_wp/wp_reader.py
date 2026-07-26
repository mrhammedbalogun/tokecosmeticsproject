"""Read-only SQL layer over the live WooCommerce database.

Touches exactly five tables: posts, postmeta, terms, term_taxonomy,
term_relationships. The MariaDB user this runs as is granted SELECT on those
five and nothing else, so a compromise here cannot reach wp_users or any order
table. Returns plain dicts — no Django models, no transformation.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

import pymysql
from django.conf import settings

logger = logging.getLogger(__name__)


@contextmanager
def wp_connection():
    if not settings.WP_DB_NAME:
        raise RuntimeError(
            "WP_DB_* settings are unset. Pass them per-invocation, e.g.\n"
            "  docker compose run --rm -e WP_DB_USER=wp_readonly -e WP_DB_PASSWORD=... web \\\n"
            "    python manage.py extract_wp_catalog --out /mnt/exports/catalog-export.json"
        )
    conn = pymysql.connect(
        host=settings.WP_DB_HOST,
        port=settings.WP_DB_PORT,
        user=settings.WP_DB_USER,
        password=settings.WP_DB_PASSWORD,
        database=settings.WP_DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        yield conn
    finally:
        conn.close()


def _p(table: str) -> str:
    return f"{settings.WP_TABLE_PREFIX}{table}"


def fetch_products(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT ID, post_title, post_name AS slug, post_content, post_excerpt,
                       post_status, post_date_gmt
                FROM {_p('posts')}
                WHERE post_type='product' AND post_status IN ('publish','draft')
                ORDER BY ID"""
        )
        return list(cur.fetchall())


def fetch_variations(conn, parent_ids: list[int]) -> list[dict]:
    if not parent_ids:
        return []
    placeholders = ",".join(["%s"] * len(parent_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT ID, post_parent, post_title, post_name AS slug, menu_order
                FROM {_p('posts')}
                WHERE post_type='product_variation' AND post_status='publish'
                  AND post_parent IN ({placeholders})
                ORDER BY post_parent, menu_order, ID""",
            parent_ids,
        )
        return list(cur.fetchall())


def fetch_meta(conn, post_ids: list[int]) -> dict[int, dict[str, str]]:
    """All postmeta for the given posts, pivoted to {post_id: {key: value}}.

    ACF stores the value under `Benefits` and the field key under `_Benefits`;
    both come back and the caller reads the non-underscore key.
    """
    if not post_ids:
        return {}
    placeholders = ",".join(["%s"] * len(post_ids))
    out: dict[int, dict[str, str]] = {pid: {} for pid in post_ids}
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT post_id, meta_key, meta_value FROM {_p('postmeta')}
                WHERE post_id IN ({placeholders})""",
            post_ids,
        )
        for row in cur.fetchall():
            out[row["post_id"]][row["meta_key"]] = row["meta_value"]
    return out


def fetch_terms(conn) -> list[dict]:
    """Categories, tags and pa_* attribute terms in one pass."""
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT t.term_id, t.name, t.slug, tt.taxonomy, tt.parent, tt.description
                FROM {_p('terms')} t
                JOIN {_p('term_taxonomy')} tt USING(term_id)
                WHERE tt.taxonomy IN ('product_cat','product_tag') OR tt.taxonomy LIKE 'pa_%%'
                ORDER BY tt.parent, t.name"""
        )
        return list(cur.fetchall())


def fetch_term_links(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT tr.object_id, tt.taxonomy, t.term_id, t.slug
                FROM {_p('term_relationships')} tr
                JOIN {_p('term_taxonomy')} tt ON tr.term_taxonomy_id=tt.term_taxonomy_id
                JOIN {_p('terms')} t ON tt.term_id=t.term_id
                WHERE tt.taxonomy IN ('product_cat','product_tag')"""
        )
        return list(cur.fetchall())


def fetch_attachment_paths(conn, attachment_ids: list[int]) -> dict[int, str]:
    """{attachment_id: '2025/11/toke-shea.jpg'} relative to the uploads root."""
    if not attachment_ids:
        return {}
    placeholders = ",".join(["%s"] * len(attachment_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT post_id, meta_value FROM {_p('postmeta')}
                WHERE meta_key='_wp_attached_file' AND post_id IN ({placeholders})""",
            attachment_ids,
        )
        return {r["post_id"]: r["meta_value"] for r in cur.fetchall()}
