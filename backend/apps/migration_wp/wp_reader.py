"""Read-only SQL layer over the live WooCommerce database.

TWO CREDENTIALS, TWO REACHES — the distinction is the security property, so read this
before adding a query.

* **Catalogue** (`fetch_products`/`fetch_variations`/`fetch_meta`/`fetch_terms`/
  `fetch_term_links`/`fetch_attachment_paths`) runs as **`wp_readonly`**, which holds
  SELECT on exactly five tables: posts, postmeta, terms, term_taxonomy,
  term_relationships. This is the RECURRING import. It cannot reach `wp_users`, and it
  must stay that way: a permanently-installed job with access to password hashes is a
  standing liability, not a convenience.

* **Customers** (`fetch_customers`, Plan-22) runs as **`wp_migration`** — a separate,
  short-lived user created at extract time and DROPped after the Plan-27 cutover. It adds
  users, usermeta and the order tables. Nothing in this module chooses which credential it
  gets; that is the caller's environment, and the whole reason the two are separate users
  rather than one widened one.

Returns plain dicts — no Django models, no transformation.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

import pymysql
from django.conf import settings

logger = logging.getLogger(__name__)

# Postmeta noise floor: real WooCommerce products carry dozens of internal
# keys (_edit_lock, _edit_last, total_sales, _elementor_page_assets, the ACF
# `_Benefits`-style field-key twins, ...) that the import never reads and that
# only bloat the human review artifact. Keep exactly what transform.py or the
# extract command consumes; everything else is dropped (and logged — see
# fetch_meta) rather than silently carried along.
_META_KEYS_EXACT = frozenset(
    {
        "_sku",
        "_regular_price",
        "_sale_price",
        "_sale_price_dates_from",
        "_sale_price_dates_to",
        "_stock",
        "_stock_status",
        "_manage_stock",
        "_weight",
        "_thumbnail_id",
        "_product_image_gallery",
        "_product_attributes",
        "Benefits",
        "product_main_usp",
    }
)
_META_KEY_PREFIXES = (
    "attribute_",
    "product_usp_",
    "Testimonial_",
    "Small_Image_",
    "Medium_Image_",
)


def _is_kept_meta_key(key: str) -> bool:
    return key in _META_KEYS_EXACT or key.startswith(_META_KEY_PREFIXES)


@contextmanager
def wp_connection():
    if not settings.WP_DB_NAME:
        raise RuntimeError(
            "WP_DB_* settings are unset. Pass them per-invocation, e.g.\n"
            "  docker compose run --rm -e WP_DB_USER=wp_readonly -e WP_DB_PASSWORD=... web \\\n"
            "    python manage.py extract_wp_catalog --out /mnt/exports/catalog-export.json"
        )
    # WP_DB_HOST doubles as a socket path when it starts with "/". MariaDB on
    # the VPS binds 127.0.0.1 only (/etc/my.cnf: bind-address=127.0.0.1), so a
    # container cannot reach it over TCP at all; it dials a bind-mounted
    # /var/lib/mysql/mysql.sock instead. That is also why the grant is
    # 'wp_readonly'@'localhost' — a socket connection authenticates as
    # localhost. Rebinding MariaDB to reach it over the docker bridge would
    # mean restarting the database behind the live WordPress store, and would
    # leave it listening on a box where ufw is inactive; the socket costs
    # neither. pymysql ignores host/port when unix_socket is set, so they are
    # omitted rather than passed alongside.
    if settings.WP_DB_HOST.startswith("/"):
        endpoint = {"unix_socket": settings.WP_DB_HOST}
    else:
        endpoint = {"host": settings.WP_DB_HOST, "port": settings.WP_DB_PORT}
    conn = pymysql.connect(
        **endpoint,
        user=settings.WP_DB_USER,
        password=settings.WP_DB_PASSWORD,
        database=settings.WP_DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        # This runs once against a live box that's simultaneously serving the
        # storefront: a stalled query must fail loudly, not hang the
        # connection open indefinitely.
        read_timeout=60,
        write_timeout=60,
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
    """Published variations only.

    Deliberately asymmetric with fetch_products: products are pulled for both
    'publish' and 'draft' (69 + 2 = 71 rows, measured 2026-07-26) so the
    reviewer can see what is being excluded — notably the 27 rows left in
    WooCommerce's 'importing' status, which no filter here will ever pick up.
    Variations, by contrast, are import candidates only — a draft variation
    isn't sellable and doesn't need to reach the artifact, so only 'publish'
    rows are fetched here.
    """
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
    """All *relevant* postmeta for the given posts, pivoted to {post_id: {key: value}}.

    ACF stores the value under `Benefits` and the field key under `_Benefits`;
    both come back from WordPress, but only the non-underscore key passes the
    allowlist below — the field-key twin (e.g. `field_68e62397bfcc9`) is noise
    for this artifact. Keys outside the allowlist are dropped and the distinct
    set of dropped names is logged once at INFO, so a future WordPress plugin
    introducing a key we actually need doesn't disappear invisibly.
    """
    if not post_ids:
        return {}
    placeholders = ",".join(["%s"] * len(post_ids))
    out: dict[int, dict[str, str]] = {pid: {} for pid in post_ids}
    dropped_keys: set[str] = set()
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT post_id, meta_key, meta_value FROM {_p('postmeta')}
                WHERE post_id IN ({placeholders})""",
            post_ids,
        )
        for row in cur.fetchall():
            key = row["meta_key"]
            if _is_kept_meta_key(key):
                out[row["post_id"]][key] = row["meta_value"]
            else:
                dropped_keys.add(key)
    if dropped_keys:
        logger.info(
            "Dropped %d unused meta keys: %s",
            len(dropped_keys),
            ", ".join(sorted(dropped_keys)),
        )
    return out


def fetch_terms(conn) -> list[dict]:
    """Categories, tags and pa_* attribute terms in one pass.

    No params are passed to this execute() call, so pymysql's %-placeholder
    substitution never runs — MariaDB receives the literal string 'pa_%%',
    and LIKE collapses the doubled '%' into a single wildcard. Kept doubled
    (rather than simplified to a single '%') so this stays correct if params
    are ever added to this query.
    """
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
    """{attachment_id: '2025/11/toke-shea.jpg'} relative to the uploads root.

    A requested ID with no `_wp_attached_file` row is simply absent from the
    returned dict — that's indistinguishable, on its own, from "this product
    never had an image." So any gap is logged as a WARNING here (names only,
    just IDs); the caller additionally surfaces the same list in the artifact
    under "missing_attachments" so a reviewer sees it too, not just an operator
    tailing logs.
    """
    if not attachment_ids:
        return {}
    placeholders = ",".join(["%s"] * len(attachment_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT post_id, meta_value FROM {_p('postmeta')}
                WHERE meta_key='_wp_attached_file' AND post_id IN ({placeholders})""",
            attachment_ids,
        )
        found = {r["post_id"]: r["meta_value"] for r in cur.fetchall()}
    missing = sorted(set(attachment_ids) - set(found.keys()))
    if missing:
        logger.warning(
            "Missing _wp_attached_file for %d requested attachment ids: %s",
            len(missing),
            missing,
        )
    return found


# ── customers (Plan-22) ──────────────────────────────────────────────────────────────────

#: The ONLY usermeta keys that leave the server. An allow-list, not a deny-list, and the
#: reason is one key: `session_tokens` holds LIVE SESSION MATERIAL for the running store.
#: A deny-list would carry it the first time a plugin renamed something, and the extract
#: artifact would then be a file that grants login to the WordPress site it came from.
#: Everything here is a name or a phone number, all of which the customer already gave us.
_USER_META_KEYS = frozenset(
    {
        "first_name",
        "last_name",
        "billing_first_name",
        "billing_last_name",
        "billing_phone",
    }
)


def fetch_customers(conn) -> list[dict]:
    """Users with AT LEAST ONE ORDER. Never every user.

    THE FILTER IS DOING SECURITY WORK, not tidiness. These stores are under an automated
    signup flood — the intl store went from 51 users on 14 July to 3,284 on 1 August, of
    which ZERO have ever placed an order, and it was still climbing while this was being
    written. Migrating "all users" would import several thousand accounts created by
    whoever is running that, hand them password hashes on the new platform, and make the
    abuse permanent. `EXISTS (an order)` is the cheapest possible statement of "this is a
    real customer" and it excludes every one of them.

    `customer_id > 0` because WooCommerce writes 0 for guest checkouts, which have no user
    row to migrate — they become Plan-23's guest orders instead.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT u.ID, u.user_email, u.user_pass, u.user_login,
                       u.display_name, u.user_registered
                FROM {_p('users')} u
                WHERE EXISTS (
                    SELECT 1 FROM {_p('wc_orders')} o
                    WHERE o.customer_id = u.ID AND o.customer_id > 0
                )
                ORDER BY u.ID"""
        )
        return list(cur.fetchall())


def fetch_user_meta(conn, user_ids: list[int]) -> dict[int, dict[str, str]]:
    """Allow-listed usermeta for the given users, pivoted to {user_id: {key: value}}.

    Mirrors `fetch_meta`, including logging the distinct dropped keys once at INFO, so a
    plugin that starts storing something we need does not vanish silently. Unlike
    `fetch_meta` this list has no prefix rules — every key is spelled out, because the
    cost of an over-broad match here is exporting session tokens.
    """
    if not user_ids:
        return {}
    placeholders = ",".join(["%s"] * len(user_ids))
    out: dict[int, dict[str, str]] = {uid: {} for uid in user_ids}
    dropped_keys: set[str] = set()
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT user_id, meta_key, meta_value FROM {_p('usermeta')}
                WHERE user_id IN ({placeholders})""",
            user_ids,
        )
        for row in cur.fetchall():
            key = row["meta_key"]
            if key in _USER_META_KEYS:
                out[row["user_id"]][key] = row["meta_value"]
            else:
                dropped_keys.add(key)
    if dropped_keys:
        logger.info(
            "Dropped %d usermeta keys not on the allow-list: %s",
            len(dropped_keys),
            ", ".join(sorted(dropped_keys)),
        )
    return out
