# Plan-21 Product Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate 69 published WooCommerce products (plus variants, categories, tags, prices, stock, images and ACF marketing content) into the production platform, so `next.tokecosmetics.com` shows a real catalogue.

**Architecture:** Two Django management commands split by responsibility. `extract_wp_catalog` reads MariaDB through a thin SQL layer and writes a reviewable JSON artifact; `import_catalog` consumes only that artifact and writes Postgres + S3, never touching MariaDB. All business logic lives in pure functions in `transform.py`, unit-tested without a database. `verify_catalog` reports counts, orphans and worklists.

**Tech Stack:** Django 5, Postgres 16, `pymysql` (pure-Python MySQL driver), `phpserialize`, pytest, S3 via django-storages (already configured).

**Spec:** [`docs/superpowers/specs/2026-07-25-plan-21-migration-products-design.md`](../specs/2026-07-25-plan-21-migration-products-design.md)

---

## Deviation from the spec — test fixtures

The spec proposed "a trimmed MySQL fixture dump" for tests. This plan uses a **committed JSON artifact** (`tests/fixtures/catalog-export-sample.json`) instead, because:

- CI needs no MySQL service — tests stay fast and hermetic.
- The JSON artifact is exactly what `import_catalog` consumes in production, so the fixture tests the real code path rather than a parallel one.
- The SQL layer is thin enough to cover with a single integration test that skips unless `WP_DB_*` is set in the environment.

Everything else follows the spec as written.

---

## File Structure

**Create:**

| File | Responsibility |
|---|---|
| `backend/apps/migration_wp/__init__.py` | package marker |
| `backend/apps/migration_wp/apps.py` | AppConfig |
| `backend/apps/migration_wp/wp_reader.py` | SQL only — 5 tables, returns plain dicts |
| `backend/apps/migration_wp/transform.py` | pure functions: HTML cleanup, ACF parsing, SKU generation |
| `backend/apps/migration_wp/management/commands/extract_wp_catalog.py` | MariaDB → JSON artifact |
| `backend/apps/migration_wp/management/commands/import_catalog.py` | JSON artifact → Postgres + S3 |
| `backend/apps/migration_wp/management/commands/verify_catalog.py` | reports + worklist CSVs |
| `backend/apps/migration_wp/tests/fixtures/catalog-export-sample.json` | 6-product fixture |
| `backend/apps/migration_wp/tests/test_transform.py` | pure-function tests |
| `backend/apps/migration_wp/tests/test_import_catalog.py` | import behaviour |
| `backend/apps/migration_wp/tests/test_idempotency.py` | re-run safety, the clobber guard |
| `backend/apps/migration_wp/tests/test_wp_reader.py` | integration, skipped without `WP_DB_*` |

**Modify:**

| File | Change |
|---|---|
| `backend/apps/catalog/models.py` | add `Category.legacy_wp_id`, `Product.usps`, `Product.testimonials` |
| `backend/config/settings/base.py` | `WP_DB_*` env config, register `apps.migration_wp` |
| `backend/pyproject.toml` | add `pymysql`, `phpserialize` |
| `infra/docker-compose.prod.yml` | read-only uploads mount + exports volume |
| `docs/audit.md` | correct the three disproven claims |

---

## Task 1: App scaffold, dependencies and model fields

**Files:**
- Create: `backend/apps/migration_wp/__init__.py`, `backend/apps/migration_wp/apps.py`
- Create: `backend/apps/migration_wp/management/__init__.py`, `backend/apps/migration_wp/management/commands/__init__.py`
- Create: `backend/apps/migration_wp/tests/__init__.py`
- Modify: `backend/apps/catalog/models.py`
- Modify: `backend/config/settings/base.py`
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add dependencies**

In `backend/pyproject.toml`, add to the `dependencies` list:

```toml
    "pymysql>=1.1.0",
    "phpserialize>=1.3",
```

Then run:

```bash
cd backend && uv sync
```

- [ ] **Step 2: Create the package files**

`backend/apps/migration_wp/__init__.py` — empty file.

`backend/apps/migration_wp/apps.py`:

```python
from django.apps import AppConfig


class MigrationWpConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.migration_wp"
    verbose_name = "WordPress migration"
```

Create empty `__init__.py` in `management/`, `management/commands/`, `tests/`, and `tests/fixtures/`.

- [ ] **Step 3: Register the app and WP_DB settings**

In `backend/config/settings/base.py`, add `"apps.migration_wp",` to `INSTALLED_APPS` (after the other `apps.*` entries).

Then add near the other env-driven config:

```python
# WordPress migration source (Plan-21). Deliberately unset in normal operation:
# credentials are passed per-invocation to `extract_wp_catalog` only, against a
# MariaDB user granted SELECT on five wp_* tables and nothing else. `import_catalog`
# never reads these.
WP_DB_HOST = env("WP_DB_HOST", default="")
WP_DB_PORT = env.int("WP_DB_PORT", default=3306)
WP_DB_NAME = env("WP_DB_NAME", default="")
WP_DB_USER = env("WP_DB_USER", default="")
WP_DB_PASSWORD = env("WP_DB_PASSWORD", default="")
WP_TABLE_PREFIX = env("WP_TABLE_PREFIX", default="wp_")
```

- [ ] **Step 4: Add the three model fields**

In `backend/apps/catalog/models.py`, add to `Category` (after `sort_order`):

```python
    legacy_wp_id = models.IntegerField(null=True, blank=True, db_index=True)
```

Add to `Product` (after `legacy_wp_id`):

```python
    # Plan-21: marketing content migrated from WooCommerce ACF fields.
    # usps: ["Daily hydration, all-day softness.", ...]
    usps = models.JSONField(default=list, blank=True)
    # testimonials: [{"name":.., "text":.., "skin_concern":.., "qty_bought":..}]
    # NOT reviews — these carry no rating and must never touch rating_avg/rating_count
    # or the schema.org aggregateRating in storefront/src/lib/seo.ts.
    testimonials = models.JSONField(default=list, blank=True)
```

- [ ] **Step 5: Generate and apply the migration**

```bash
cd backend && .venv/Scripts/python.exe manage.py makemigrations catalog migration_wp
```

Expected: one new migration in `apps/catalog/migrations/` adding three fields. `migration_wp` has no models, so it produces nothing.

```bash
cd backend && .venv/Scripts/python.exe manage.py migrate
```

Expected: `Applying catalog.00XX_... OK`

- [ ] **Step 6: Verify the suite still passes**

```bash
cd backend && .venv/Scripts/python.exe -m pytest -q --no-header
```

Expected: 550 passed, 1 skipped (unchanged from the Plan-02 baseline).

- [ ] **Step 7: Commit**

```bash
git add backend/apps/migration_wp backend/apps/catalog backend/config/settings/base.py backend/pyproject.toml backend/uv.lock
git commit -m "feat(migration): scaffold migration_wp app and catalog fields for Plan-21"
```

---

## Task 2: Description cleaning

The source HTML is clean prose but carries editor artifacts: `data-start="162"` / `data-end="542"` attributes on tags, and trailing `&nbsp;`.

**Files:**
- Create: `backend/apps/migration_wp/transform.py`
- Create: `backend/apps/migration_wp/tests/test_transform.py`

- [ ] **Step 1: Write the failing test**

`backend/apps/migration_wp/tests/test_transform.py`:

```python
from apps.migration_wp.transform import clean_description


def test_strips_editor_data_attributes():
    raw = '<p data-start="162" data-end="542">Nourish your skin every day.</p>'
    assert clean_description(raw) == "<p>Nourish your skin every day.</p>"


def test_strips_nbsp_entities_and_trims():
    raw = "Toke shea butter is a daily moisturizer.\n&nbsp;\n"
    assert clean_description(raw) == "Toke shea butter is a daily moisturizer."


def test_preserves_real_markup():
    raw = '<strong data-start="251" data-end="267">no chemicals</strong> inside'
    assert clean_description(raw) == "<strong>no chemicals</strong> inside"


def test_empty_input_returns_empty_string():
    assert clean_description("") == ""
    assert clean_description(None) == ""
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp/tests/test_transform.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'apps.migration_wp.transform'`

- [ ] **Step 3: Write the implementation**

`backend/apps/migration_wp/transform.py`:

```python
"""Pure transforms from WordPress shapes to platform shapes.

Every function here takes plain data and returns plain data — no Django models,
no database, no network. That keeps the migration's real logic unit-testable
without a MySQL service in CI.
"""
from __future__ import annotations

import re

# Editor paste artifacts: <p data-start="162" data-end="542">
_DATA_ATTR_RE = re.compile(r'\s+data-(?:start|end)="[^"]*"')
_NBSP_RE = re.compile(r"(&nbsp;| )")


def clean_description(html: str | None) -> str:
    """Strip editor artifacts from WooCommerce product HTML.

    The content is human-written prose in simple HTML (verified 2026-07-25:
    no Elementor, no shortcodes, no embedded images). Only two artifacts need
    removing, and real markup must survive untouched.
    """
    if not html:
        return ""
    out = _DATA_ATTR_RE.sub("", html)
    out = _NBSP_RE.sub(" ", out)
    return out.strip()
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp/tests/test_transform.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/apps/migration_wp/transform.py backend/apps/migration_wp/tests/test_transform.py
git commit -m "feat(migration): clean WooCommerce description artifacts"
```

---

## Task 3: Benefits, USPs and testimonials from ACF meta

ACF stores the value under `Benefits` and the field key under `_Benefits`. The importer must read the former and ignore the latter.

`Benefits` arrives as one string with sentences separated by runs of two or more spaces:
`"Deeply moisturizes and hydrates dry skin.  Soothes eczema and sensitive skin irritation.  ..."`

**Files:**
- Modify: `backend/apps/migration_wp/transform.py`
- Modify: `backend/apps/migration_wp/tests/test_transform.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/apps/migration_wp/tests/test_transform.py`:

```python
from apps.migration_wp.transform import (
    append_benefits,
    parse_benefits,
    parse_testimonials,
    parse_usps,
)


def test_parse_benefits_splits_on_double_space():
    raw = "Deeply moisturizes dry skin.  Soothes eczema.  Prevents flakiness."
    assert parse_benefits(raw) == [
        "Deeply moisturizes dry skin.",
        "Soothes eczema.",
        "Prevents flakiness.",
    ]


def test_parse_benefits_empty_returns_empty_list():
    assert parse_benefits("") == []
    assert parse_benefits(None) == []


def test_append_benefits_adds_ul_to_description():
    html = append_benefits("<p>Body cream.</p>", ["Soft skin.", "No irritation."])
    assert html == (
        "<p>Body cream.</p>\n"
        "<h3>Benefits</h3>\n"
        "<ul><li>Soft skin.</li><li>No irritation.</li></ul>"
    )


def test_append_benefits_with_no_benefits_returns_description_unchanged():
    assert append_benefits("<p>Body cream.</p>", []) == "<p>Body cream.</p>"


def test_parse_usps_reads_main_then_numbered_in_order():
    meta = {
        "product_main_usp": "Daily hydration, all-day softness.",
        "product_usp_1": "Relieves eczema.",
        "product_usp_3": "Absorbs fast.",
        "product_usp_4": "Smooths and protects.",
    }
    assert parse_usps(meta) == [
        "Daily hydration, all-day softness.",
        "Relieves eczema.",
        "Absorbs fast.",
        "Smooths and protects.",
    ]


def test_parse_usps_ignores_blank_and_missing():
    assert parse_usps({"product_main_usp": "", "product_usp_2": "   "}) == []


def test_parse_testimonials_groups_by_index():
    meta = {
        "Testimonial_1_Customer_Name": "Mayowa - Osogbo",
        "Testimonial_1_Review_Text": "My skin feels nourished.",
        "Testimonial_1_Skin_Concern": "",
        "Testimonial_1_Number_of_Item_Bought": "1",
        "Testimonial_2_Customer_Name": "Ada - Lagos",
        "Testimonial_2_Review_Text": "Gentle on my baby.",
        "Testimonial_2_Skin_Concern": "Eczema",
        "Testimonial_2_Number_of_Item_Bought": "3",
    }
    assert parse_testimonials(meta) == [
        {
            "name": "Mayowa - Osogbo",
            "text": "My skin feels nourished.",
            "skin_concern": "",
            "qty_bought": 1,
        },
        {
            "name": "Ada - Lagos",
            "text": "Gentle on my baby.",
            "skin_concern": "Eczema",
            "qty_bought": 3,
        },
    ]


def test_parse_testimonials_skips_entries_with_no_review_text():
    meta = {
        "Testimonial_1_Customer_Name": "Nobody",
        "Testimonial_1_Review_Text": "",
        "Testimonial_2_Customer_Name": "Ada",
        "Testimonial_2_Review_Text": "Great product.",
    }
    result = parse_testimonials(meta)
    assert len(result) == 1
    assert result[0]["name"] == "Ada"


def test_parse_testimonials_tolerates_non_numeric_quantity():
    meta = {
        "Testimonial_1_Review_Text": "Good.",
        "Testimonial_1_Number_of_Item_Bought": "a few",
    }
    assert parse_testimonials(meta)[0]["qty_bought"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp/tests/test_transform.py -v
```

Expected: FAIL — `ImportError: cannot import name 'append_benefits'`

- [ ] **Step 3: Write the implementation**

Append to `backend/apps/migration_wp/transform.py`:

```python
import html as html_lib

_BENEFIT_SPLIT_RE = re.compile(r"\s{2,}")
_TESTIMONIAL_SLOTS = (1, 2, 3)


def parse_benefits(raw: str | None) -> list[str]:
    """Split the ACF `Benefits` blob into individual benefit sentences.

    Source format is one string with sentences separated by runs of 2+ spaces.
    """
    if not raw:
        return []
    return [part.strip() for part in _BENEFIT_SPLIT_RE.split(raw.strip()) if part.strip()]


def append_benefits(description: str, benefits: list[str]) -> str:
    """Append benefits as a bulleted list so they render in the PDP Description
    accordion (storefront/src/components/product/PdpAccordions.tsx) without
    needing a new storefront section.
    """
    if not benefits:
        return description
    items = "".join(f"<li>{html_lib.escape(b)}</li>" for b in benefits)
    return f"{description}\n<h3>Benefits</h3>\n<ul>{items}</ul>"


def parse_usps(meta: dict[str, str]) -> list[str]:
    """Main USP first, then product_usp_1..4 in order. Blanks dropped."""
    keys = ["product_main_usp"] + [f"product_usp_{i}" for i in range(1, 5)]
    return [meta[k].strip() for k in keys if (meta.get(k) or "").strip()]


def parse_testimonials(meta: dict[str, str]) -> list[dict]:
    """Group the flat Testimonial_N_* ACF keys into records.

    An entry with no review text is not a testimonial — skip it. These become
    Product.testimonials and must NEVER become Review rows: the source carries
    no rating, and inventing one would publish a fabricated schema.org
    aggregateRating (see storefront/src/lib/seo.ts:154).
    """
    out: list[dict] = []
    for i in _TESTIMONIAL_SLOTS:
        text = (meta.get(f"Testimonial_{i}_Review_Text") or "").strip()
        if not text:
            continue
        raw_qty = (meta.get(f"Testimonial_{i}_Number_of_Item_Bought") or "").strip()
        try:
            qty = int(raw_qty)
        except ValueError:
            qty = None
        out.append(
            {
                "name": (meta.get(f"Testimonial_{i}_Customer_Name") or "").strip(),
                "text": text,
                "skin_concern": (meta.get(f"Testimonial_{i}_Skin_Concern") or "").strip(),
                "qty_bought": qty,
            }
        )
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp/tests/test_transform.py -v
```

Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add backend/apps/migration_wp/transform.py backend/apps/migration_wp/tests/test_transform.py
git commit -m "feat(migration): parse ACF benefits, USPs and testimonials"
```

---

## Task 4: SKU generation and variant option values

`ProductVariant` has no `legacy_wp_id`; `sku` is unique and therefore *is* the idempotency key. A variation's SKU must derive from the **variation's own post ID**. Using the parent product ID would collide across all 71 variations and silently merge them.

**Files:**
- Modify: `backend/apps/migration_wp/transform.py`
- Modify: `backend/apps/migration_wp/tests/test_transform.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/apps/migration_wp/tests/test_transform.py`:

```python
from apps.migration_wp.transform import generate_sku, parse_option_values


def test_generate_sku_prefers_real_sku():
    assert generate_sku(existing_sku="TOKE-SHEA-50", wp_id=1234) == "TOKE-SHEA-50"


def test_generate_sku_falls_back_to_wp_id():
    assert generate_sku(existing_sku="", wp_id=1234) == "TC-WP-1234"
    assert generate_sku(existing_sku=None, wp_id=99) == "TC-WP-99"


def test_generate_sku_uses_variation_id_not_parent():
    """The whole point: two variations of one parent must not collide."""
    a = generate_sku(existing_sku="", wp_id=5001)
    b = generate_sku(existing_sku="", wp_id=5002)
    assert a != b


def test_parse_option_values_maps_taxonomy_axis_to_term_name():
    attrs = {"attribute_pa_product-size": "50ml"}
    term_names = {("pa_product-size", "50ml"): "50 ml"}
    assert parse_option_values(attrs, term_names) == {"Product Size": "50 ml"}


def test_parse_option_values_handles_non_taxonomy_axis():
    """shea-variant is a raw meta axis, not a pa_* taxonomy (4 variations use it)."""
    assert parse_option_values({"attribute_shea-variant": "Unscented"}, {}) == {
        "Shea Variant": "Unscented"
    }


def test_parse_option_values_falls_back_to_slug_when_term_missing():
    attrs = {"attribute_pa_size": "large"}
    assert parse_option_values(attrs, {}) == {"Size": "large"}


def test_parse_option_values_ignores_blank_values():
    assert parse_option_values({"attribute_pa_size": ""}, {}) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp/tests/test_transform.py -v
```

Expected: FAIL — `ImportError: cannot import name 'generate_sku'`

- [ ] **Step 3: Write the implementation**

Append to `backend/apps/migration_wp/transform.py`:

```python
SKU_PREFIX = "TC-WP-"


def generate_sku(existing_sku: str | None, wp_id: int) -> str:
    """Real SKU if WooCommerce has one, else a generated stable fallback.

    Only 1 SKU exists across the whole catalogue (audited 2026-07-25), so the
    fallback is the primary path. `wp_id` MUST be the ID of the row the variant
    represents — the variation's post ID for variable products, the product's
    post ID for simple ones. Passing a parent ID for variations collides.
    """
    if existing_sku and existing_sku.strip():
        return existing_sku.strip()
    return f"{SKU_PREFIX}{wp_id}"


def _axis_label(axis: str) -> str:
    """`attribute_pa_product-size` -> `Product Size`; `attribute_shea-variant` -> `Shea Variant`."""
    name = axis[len("attribute_"):] if axis.startswith("attribute_") else axis
    if name.startswith("pa_"):
        name = name[3:]
    return name.replace("-", " ").replace("_", " ").title()


def parse_option_values(
    attributes: dict[str, str], term_names: dict[tuple[str, str], str]
) -> dict[str, str]:
    """Build ProductVariant.option_values from a variation's attribute_* meta.

    `term_names` maps (taxonomy, term_slug) -> human term name, so taxonomy-backed
    axes show "50 ml" rather than the slug. Non-taxonomy axes (shea-variant) and
    unmapped slugs fall back to the raw value.
    """
    out: dict[str, str] = {}
    for axis, value in attributes.items():
        if not value or not value.strip():
            continue
        taxonomy = axis[len("attribute_"):] if axis.startswith("attribute_") else axis
        out[_axis_label(axis)] = term_names.get((taxonomy, value), value)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp/tests/test_transform.py -v
```

Expected: 20 passed

- [ ] **Step 5: Commit**

```bash
git add backend/apps/migration_wp/transform.py backend/apps/migration_wp/tests/test_transform.py
git commit -m "feat(migration): SKU generation keyed on variation id, option value parsing"
```

---

## Task 5: The SQL reader

**Files:**
- Create: `backend/apps/migration_wp/wp_reader.py`
- Create: `backend/apps/migration_wp/tests/test_wp_reader.py`

- [ ] **Step 1: Write the reader**

`backend/apps/migration_wp/wp_reader.py`:

```python
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
```

- [ ] **Step 2: Write the integration test**

`backend/apps/migration_wp/tests/test_wp_reader.py`:

```python
"""Integration tests against a real WordPress database.

Skipped unless WP_DB_NAME is configured, so CI stays hermetic. Run manually on
the VPS after creating the wp_readonly grant (Task 13).
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
```

- [ ] **Step 3: Run the suite — the integration test should skip**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp -v
```

Expected: 20 passed, 3 skipped

- [ ] **Step 4: Commit**

```bash
git add backend/apps/migration_wp/wp_reader.py backend/apps/migration_wp/tests/test_wp_reader.py
git commit -m "feat(migration): read-only SQL layer over five wp_ tables"
```

---

## Task 6: The extract command

**Files:**
- Create: `backend/apps/migration_wp/management/commands/extract_wp_catalog.py`

- [ ] **Step 1: Write the command**

```python
"""Read WooCommerce and write a reviewable JSON artifact.

This is the ONLY command that opens a MariaDB connection. Credentials come from
the environment per-invocation and are never stored in .env.prod.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.migration_wp import wp_reader

ARTIFACT_VERSION = 1


class Command(BaseCommand):
    help = "Extract the WooCommerce catalogue to a JSON artifact."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="path to write the JSON artifact")

    def handle(self, *args, **options):
        out_path = Path(options["out"])
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with wp_reader.wp_connection() as conn:
            products = wp_reader.fetch_products(conn)
            product_ids = [p["ID"] for p in products]
            variations = wp_reader.fetch_variations(conn, product_ids)
            variation_ids = [v["ID"] for v in variations]
            meta = wp_reader.fetch_meta(conn, product_ids + variation_ids)
            terms = wp_reader.fetch_terms(conn)
            term_links = wp_reader.fetch_term_links(conn)

            attachment_ids = self._collect_attachment_ids(product_ids, meta)
            attachments = wp_reader.fetch_attachment_paths(conn, attachment_ids)

        artifact = {
            "version": ARTIFACT_VERSION,
            "source": "wp_ng",
            "products": products,
            "variations": variations,
            "meta": {str(k): v for k, v in meta.items()},
            "terms": terms,
            "term_links": term_links,
            "attachments": {str(k): v for k, v in attachments.items()},
        }
        out_path.write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {out_path}: {len(products)} products, {len(variations)} variations, "
                f"{len(terms)} terms, {len(attachments)} attachments"
            )
        )

    @staticmethod
    def _collect_attachment_ids(product_ids: list[int], meta: dict) -> list[int]:
        """Thumbnail + gallery + the ACF Small_Image_*/Medium_Image_* slots.

        The ACF image fields hold attachment IDs, not URLs (verified 2026-07-25).
        """
        acf_keys = [f"Small_Image_{i}" for i in range(1, 5)]
        acf_keys += [f"Medium_Image_{i}" for i in range(1, 3)]
        ids: set[int] = set()
        for pid in product_ids:
            m = meta.get(pid, {})
            if (m.get("_thumbnail_id") or "").strip().isdigit():
                ids.add(int(m["_thumbnail_id"]))
            gallery = (m.get("_product_image_gallery") or "").strip()
            for part in gallery.split(","):
                if part.strip().isdigit():
                    ids.add(int(part.strip()))
            for key in acf_keys:
                val = (m.get(key) or "").strip()
                if val.isdigit():
                    ids.add(int(val))
        return sorted(ids)
```

- [ ] **Step 2: Verify the command registers**

```bash
cd backend && .venv/Scripts/python.exe manage.py extract_wp_catalog --help
```

Expected: usage text showing `--out`.

- [ ] **Step 3: Verify it fails loudly without credentials**

```bash
cd backend && .venv/Scripts/python.exe manage.py extract_wp_catalog --out /tmp/x.json
```

Expected: `RuntimeError: WP_DB_* settings are unset.` followed by the example invocation.

- [ ] **Step 4: Commit**

```bash
git add backend/apps/migration_wp/management/commands/extract_wp_catalog.py
git commit -m "feat(migration): extract_wp_catalog writes a reviewable JSON artifact"
```

---

## Task 7: Test fixture

**Files:**
- Create: `backend/apps/migration_wp/tests/fixtures/catalog-export-sample.json`
- Create: `backend/apps/migration_wp/tests/conftest.py`

- [ ] **Step 1: Write the fixture**

Six products covering: simple with full ACF, simple with no ACF, variable with two variations, sale-priced, out-of-stock, and one with a missing image file.

`backend/apps/migration_wp/tests/fixtures/catalog-export-sample.json`:

```json
{
  "version": 1,
  "source": "wp_ng",
  "products": [
    {"ID": 101, "post_title": "Toke Scented Shea Butter", "slug": "toke-scented-shea-butter",
     "post_content": "<p data-start=\"1\" data-end=\"9\">A daily moisturizer.</p>&nbsp;",
     "post_excerpt": "Daily shea butter.", "post_status": "publish",
     "post_date_gmt": "2025-11-24 10:00:00"},
    {"ID": 102, "post_title": "Toke Coconut Oil", "slug": "toke-coconut-oil",
     "post_content": "Pure multipurpose oil.", "post_excerpt": "", "post_status": "publish",
     "post_date_gmt": "2025-11-25 10:00:00"},
    {"ID": 103, "post_title": "Toke Body Lotion", "slug": "toke-body-lotion",
     "post_content": "Variable product.", "post_excerpt": "", "post_status": "publish",
     "post_date_gmt": "2025-11-26 10:00:00"},
    {"ID": 104, "post_title": "Toke Black Soap", "slug": "toke-black-soap",
     "post_content": "On sale.", "post_excerpt": "", "post_status": "publish",
     "post_date_gmt": "2025-11-27 10:00:00"},
    {"ID": 105, "post_title": "Toke Hair Food", "slug": "toke-hair-food",
     "post_content": "Currently unavailable.", "post_excerpt": "", "post_status": "publish",
     "post_date_gmt": "2025-11-28 10:00:00"},
    {"ID": 106, "post_title": "Toke Draft Item", "slug": "toke-draft-item",
     "post_content": "Not published.", "post_excerpt": "", "post_status": "draft",
     "post_date_gmt": "2025-11-29 10:00:00"}
  ],
  "variations": [
    {"ID": 5001, "post_parent": 103, "post_title": "Toke Body Lotion - 100ml",
     "slug": "toke-body-lotion-100ml", "menu_order": 0},
    {"ID": 5002, "post_parent": 103, "post_title": "Toke Body Lotion - 250ml",
     "slug": "toke-body-lotion-250ml", "menu_order": 1}
  ],
  "meta": {
    "101": {
      "_sku": "", "_regular_price": "5000", "_stock_status": "instock",
      "_thumbnail_id": "9001", "_product_image_gallery": "9002",
      "Benefits": "Deeply moisturizes dry skin.  Soothes eczema.",
      "_Benefits": "field_68e62397bfcc9",
      "product_main_usp": "Daily hydration, all-day softness.",
      "product_usp_1": "Relieves eczema.",
      "Testimonial_1_Customer_Name": "Mayowa - Osogbo",
      "Testimonial_1_Review_Text": "My skin feels nourished.",
      "Testimonial_1_Skin_Concern": "",
      "Testimonial_1_Number_of_Item_Bought": "1",
      "Small_Image_1": "9003"
    },
    "102": {"_sku": "TOKE-COCO", "_regular_price": "3500", "_stock_status": "instock",
            "_thumbnail_id": "9004"},
    "103": {"_sku": "", "_stock_status": "instock", "_thumbnail_id": "9005"},
    "104": {"_sku": "", "_regular_price": "2000", "_sale_price": "1500",
            "_sale_price_dates_from": "1764547200", "_sale_price_dates_to": "1767225600",
            "_stock_status": "instock", "_thumbnail_id": "9006"},
    "105": {"_sku": "", "_regular_price": "4000", "_stock_status": "outofstock",
            "_thumbnail_id": "9007"},
    "106": {"_sku": "", "_regular_price": "1000", "_stock_status": "instock"},
    "5001": {"_sku": "", "_regular_price": "4000", "attribute_pa_product-size": "100ml"},
    "5002": {"_sku": "", "_regular_price": "7000", "attribute_pa_product-size": "250ml"}
  },
  "terms": [
    {"term_id": 21, "name": "Body Soaps", "slug": "body-soaps", "taxonomy": "product_cat",
     "parent": 0, "description": "Soaps for the body"},
    {"term_id": 30, "name": "Lotions", "slug": "lotions", "taxonomy": "product_cat",
     "parent": 0, "description": ""},
    {"term_id": 77, "name": "bestseller", "slug": "bestseller", "taxonomy": "product_tag",
     "parent": 0, "description": ""},
    {"term_id": 90, "name": "100 ml", "slug": "100ml", "taxonomy": "pa_product-size",
     "parent": 0, "description": ""},
    {"term_id": 91, "name": "250 ml", "slug": "250ml", "taxonomy": "pa_product-size",
     "parent": 0, "description": ""}
  ],
  "term_links": [
    {"object_id": 101, "taxonomy": "product_cat", "term_id": 21, "slug": "body-soaps"},
    {"object_id": 101, "taxonomy": "product_tag", "term_id": 77, "slug": "bestseller"},
    {"object_id": 103, "taxonomy": "product_cat", "term_id": 30, "slug": "lotions"},
    {"object_id": 104, "taxonomy": "product_cat", "term_id": 21, "slug": "body-soaps"}
  ],
  "attachments": {
    "9001": "2025/11/toke-shea.jpg",
    "9002": "2025/11/toke-shea-2.jpg",
    "9003": "2025/11/toke-shea-small.jpg",
    "9004": "2025/11/toke-coconut.jpg",
    "9005": "2025/11/toke-lotion.jpg",
    "9006": "2025/11/toke-black-soap.jpg",
    "9007": "2025/11/toke-hair-food-MISSING.jpg"
  }
}
```

- [ ] **Step 2: Write the fixture loader**

`backend/apps/migration_wp/tests/conftest.py`:

```python
import json
import shutil
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "catalog-export-sample.json"


@pytest.fixture
def artifact_path(tmp_path):
    """A copy of the sample artifact, so a test can mutate it freely."""
    dest = tmp_path / "catalog-export.json"
    shutil.copy(FIXTURE, dest)
    return dest


@pytest.fixture
def artifact():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def uploads_root(tmp_path):
    """Fake wp-content/uploads. Every attachment exists EXCEPT the -MISSING one,
    so the broken-image path gets exercised."""
    root = tmp_path / "uploads"
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for rel in data["attachments"].values():
        if "MISSING" in rel:
            continue
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        # 1x1 transparent PNG
        target.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
    return root
```

- [ ] **Step 3: Commit**

```bash
git add backend/apps/migration_wp/tests/fixtures backend/apps/migration_wp/tests/conftest.py
git commit -m "test(migration): six-product JSON fixture covering the tricky cases"
```

---

## Task 8: Import categories and tags

**Files:**
- Create: `backend/apps/migration_wp/management/commands/import_catalog.py`
- Create: `backend/apps/migration_wp/tests/test_import_catalog.py`

- [ ] **Step 1: Write the failing test**

`backend/apps/migration_wp/tests/test_import_catalog.py`:

```python
import pytest
from django.core.management import call_command

from apps.catalog.models import Category, Tag

pytestmark = pytest.mark.django_db


def test_imports_categories_preserving_slug_and_legacy_id(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")

    soaps = Category.objects.get(slug="body-soaps")
    assert soaps.name == "Body Soaps"
    assert soaps.legacy_wp_id == 21
    assert soaps.parent is None
    assert soaps.description == "Soaps for the body"
    assert Category.objects.count() == 2


def test_imports_tags(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    assert Tag.objects.filter(slug="bestseller").exists()


def test_dry_run_writes_nothing(artifact_path):
    call_command("import_catalog", str(artifact_path), "--dry-run")
    assert Category.objects.count() == 0
    assert Tag.objects.count() == 0
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp/tests/test_import_catalog.py -v
```

Expected: FAIL — `CommandError: Unknown command: 'import_catalog'`

- [ ] **Step 3: Write the command skeleton with category/tag import**

`backend/apps/migration_wp/management/commands/import_catalog.py`:

```python
"""Import a catalogue artifact into Postgres. Never opens a MariaDB connection.

Idempotent by design — see the per-object keys in the Plan-21 spec. Safe to run
repeatedly (dry run, rehearsal, cutover).
"""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Category, Tag

LEGACY_SOURCE = "wp_ng"


class Command(BaseCommand):
    help = "Import a catalogue JSON artifact produced by extract_wp_catalog."

    def add_arguments(self, parser):
        parser.add_argument("artifact", help="path to catalog-export.json")
        parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
        parser.add_argument("--skip-media", action="store_true", help="skip S3 image upload")
        parser.add_argument("--skip-stock", action="store_true", help="skip the stock phase")
        parser.add_argument(
            "--force-stock",
            action="store_true",
            help="overwrite stock a human has edited (dangerous — see spec)",
        )
        parser.add_argument(
            "--uploads-root",
            default="/mnt/wp-uploads-ng",
            help="read-only mount of wp-content/uploads",
        )

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        data = json.loads(Path(options["artifact"]).read_text(encoding="utf-8"))

        if self.dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no writes will be made"))

        with transaction.atomic():
            cats = self._import_categories(data)
            tags = self._import_tags(data)
            self.stdout.write(f"categories: {cats}  tags: {tags}")
            if self.dry_run:
                transaction.set_rollback(True)

    def _import_categories(self, data) -> int:
        """WP product_cat terms -> Category, keyed on legacy_wp_id, slug preserved."""
        terms = [t for t in data["terms"] if t["taxonomy"] == "product_cat"]
        by_wp_id: dict[int, Category] = {}
        # First pass: create/update without parents so any order works.
        for t in terms:
            cat, _ = Category.objects.update_or_create(
                legacy_wp_id=t["term_id"],
                defaults={
                    "name": t["name"],
                    "slug": t["slug"],
                    "description": t.get("description") or "",
                },
            )
            by_wp_id[t["term_id"]] = cat
        # Second pass: wire parents. All 40 live terms are flat, but a nested term
        # appearing at cutover must not silently lose its parent.
        for t in terms:
            parent_wp_id = t.get("parent") or 0
            if parent_wp_id and parent_wp_id in by_wp_id:
                cat = by_wp_id[t["term_id"]]
                cat.parent = by_wp_id[parent_wp_id]
                cat.save(update_fields=["parent"])
        return len(terms)

    def _import_tags(self, data) -> int:
        terms = [t for t in data["terms"] if t["taxonomy"] == "product_tag"]
        for t in terms:
            Tag.objects.get_or_create(slug=t["slug"], defaults={"name": t["name"]})
        return len(terms)
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp/tests/test_import_catalog.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/apps/migration_wp/management/commands/import_catalog.py backend/apps/migration_wp/tests/test_import_catalog.py
git commit -m "feat(migration): import categories and tags"
```

---

## Task 9: Import products

**Files:**
- Modify: `backend/apps/migration_wp/management/commands/import_catalog.py`
- Modify: `backend/apps/migration_wp/tests/test_import_catalog.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/apps/migration_wp/tests/test_import_catalog.py`:

```python
from apps.catalog.models import Product
from apps.reviews.models import Review


def test_imports_product_with_cleaned_description_and_benefits(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")

    p = Product.objects.get(slug="toke-scented-shea-butter")
    assert p.name == "Toke Scented Shea Butter"
    assert p.legacy_wp_id == 101
    assert p.legacy_source == "wp_ng"
    assert p.status == "active"
    assert 'data-start' not in p.description
    assert "<h3>Benefits</h3>" in p.description
    assert "<li>Deeply moisturizes dry skin.</li>" in p.description
    assert p.short_description == "Daily shea butter."


def test_usps_and_testimonials_land_in_json_fields(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")

    p = Product.objects.get(slug="toke-scented-shea-butter")
    assert p.usps == ["Daily hydration, all-day softness.", "Relieves eczema."]
    assert len(p.testimonials) == 1
    assert p.testimonials[0]["name"] == "Mayowa - Osogbo"
    assert p.testimonials[0]["qty_bought"] == 1


def test_testimonials_never_become_reviews_or_move_the_rating(artifact_path):
    """D3: the source has no rating; inventing one would publish a fake
    schema.org aggregateRating via storefront/src/lib/seo.ts."""
    call_command("import_catalog", str(artifact_path), "--skip-media")

    p = Product.objects.get(slug="toke-scented-shea-butter")
    assert Review.objects.count() == 0
    assert p.rating_count == 0
    assert p.rating_avg == 0


def test_draft_product_imports_as_draft(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    assert Product.objects.get(slug="toke-draft-item").status == "draft"


def test_categories_and_tags_are_linked(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    p = Product.objects.get(slug="toke-scented-shea-butter")
    assert list(p.categories.values_list("slug", flat=True)) == ["body-soaps"]
    assert list(p.tags.values_list("slug", flat=True)) == ["bestseller"]


def test_ingredients_directions_warnings_are_blank(artifact_path):
    """No source field exists for these — they are a manual worklist, not a bug."""
    call_command("import_catalog", str(artifact_path), "--skip-media")
    p = Product.objects.get(slug="toke-scented-shea-butter")
    assert p.ingredients == ""
    assert p.directions == ""
    assert p.warnings == ""
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp/tests/test_import_catalog.py -v
```

Expected: FAIL — `Product.DoesNotExist`

- [ ] **Step 3: Implement product import**

In `import_catalog.py`, add these imports at the top:

```python
from datetime import datetime, timezone as dt_timezone

from apps.catalog.models import Product
from apps.migration_wp.transform import (
    append_benefits,
    clean_description,
    parse_benefits,
    parse_testimonials,
    parse_usps,
)
```

Add to `handle`, inside the `transaction.atomic()` block after the tags line:

```python
            products = self._import_products(data)
            self.stdout.write(f"products: {products}")
```

Add the methods:

```python
    STATUS_MAP = {"publish": "active", "draft": "draft"}

    def _import_products(self, data) -> int:
        meta_all = data["meta"]
        links_by_object: dict[int, list[dict]] = {}
        for link in data["term_links"]:
            links_by_object.setdefault(link["object_id"], []).append(link)

        cats_by_wp_id = {c.legacy_wp_id: c for c in Category.objects.all()}
        tags_by_slug = {t.slug: t for t in Tag.objects.all()}

        count = 0
        for row in data["products"]:
            wp_id = row["ID"]
            meta = meta_all.get(str(wp_id), {})

            description = clean_description(row.get("post_content"))
            description = append_benefits(description, parse_benefits(meta.get("Benefits")))

            product, _ = Product.objects.update_or_create(
                legacy_source=LEGACY_SOURCE,
                legacy_wp_id=wp_id,
                defaults={
                    "name": row["post_title"],
                    "slug": row["slug"],
                    "description": description,
                    "short_description": clean_description(row.get("post_excerpt")),
                    "status": self.STATUS_MAP.get(row["post_status"], "draft"),
                    "published_at": self._parse_dt(row.get("post_date_gmt")),
                    "usps": parse_usps(meta),
                    "testimonials": parse_testimonials(meta),
                },
            )

            links = links_by_object.get(wp_id, [])
            product.categories.set(
                [
                    cats_by_wp_id[link["term_id"]]
                    for link in links
                    if link["taxonomy"] == "product_cat" and link["term_id"] in cats_by_wp_id
                ]
            )
            product.tags.set(
                [
                    tags_by_slug[link["slug"]]
                    for link in links
                    if link["taxonomy"] == "product_tag" and link["slug"] in tags_by_slug
                ]
            )
            count += 1
        return count

    @staticmethod
    def _parse_dt(value):
        if not value:
            return None
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=dt_timezone.utc
        )
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp/tests/test_import_catalog.py -v
```

Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add backend/apps/migration_wp
git commit -m "feat(migration): import products with ACF content, testimonials kept out of reviews"
```

---

## Task 10: Import variants and prices

`Price` has `UniqueConstraint(variant, currency, country, starts_at)`. In Postgres, NULLs compare as distinct, so two rows with `starts_at=NULL` do **not** violate it — a naive re-run would silently duplicate every base price. Prices are therefore deleted and recreated per variant inside the run's transaction.

**Files:**
- Modify: `backend/apps/migration_wp/management/commands/import_catalog.py`
- Modify: `backend/apps/migration_wp/tests/test_import_catalog.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/apps/migration_wp/tests/test_import_catalog.py`:

```python
from decimal import Decimal

from apps.catalog.models import ProductVariant
from apps.pricing.models import Price


def test_simple_product_gets_one_default_variant_with_generated_sku(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    p = Product.objects.get(slug="toke-scented-shea-butter")
    variants = list(p.variants.all())
    assert len(variants) == 1
    assert variants[0].sku == "TC-WP-101"
    assert variants[0].is_default is True


def test_existing_sku_is_preserved(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    p = Product.objects.get(slug="toke-coconut-oil")
    assert p.variants.get().sku == "TOKE-COCO"


def test_variable_product_gets_one_variant_per_variation_keyed_on_variation_id(artifact_path):
    """Regression: keying on the parent ID would collide both variations into one."""
    call_command("import_catalog", str(artifact_path), "--skip-media")
    p = Product.objects.get(slug="toke-body-lotion")
    skus = sorted(p.variants.values_list("sku", flat=True))
    assert skus == ["TC-WP-5001", "TC-WP-5002"]


def test_variant_option_values_use_term_names(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    v = ProductVariant.objects.get(sku="TC-WP-5001")
    assert v.option_values == {"Product Size": "100 ml"}


def test_regular_price_creates_one_ngn_price(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    v = ProductVariant.objects.get(sku="TC-WP-101")
    price = v.prices.get()
    assert price.amount == Decimal("5000.00")
    assert price.currency_id == "NGN"
    assert price.starts_at is None


def test_sale_price_creates_a_second_dated_row_with_compare_at(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    v = ProductVariant.objects.get(sku="TC-WP-104")
    sale = v.prices.exclude(starts_at=None).get()
    assert sale.amount == Decimal("1500.00")
    assert sale.compare_at_amount == Decimal("2000.00")
    assert sale.starts_at is not None
    assert sale.ends_at is not None
    assert v.prices.count() == 2


def test_prices_do_not_duplicate_on_rerun(artifact_path):
    """Postgres treats NULL starts_at as distinct, so the unique constraint alone
    does NOT protect against this. Delete-and-recreate is what makes it safe."""
    call_command("import_catalog", str(artifact_path), "--skip-media")
    call_command("import_catalog", str(artifact_path), "--skip-media")
    v = ProductVariant.objects.get(sku="TC-WP-101")
    assert v.prices.count() == 1
    assert Price.objects.filter(variant__sku="TC-WP-104").count() == 2
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp/tests/test_import_catalog.py -v
```

Expected: FAIL — `ProductVariant.DoesNotExist` / variants count 0

- [ ] **Step 3: Implement variants and prices**

Add imports to `import_catalog.py`:

```python
from decimal import Decimal, InvalidOperation

from apps.catalog.models import ProductVariant
from apps.core.models import Currency
from apps.migration_wp.transform import generate_sku, parse_option_values
from apps.pricing.models import Price
```

Add to `handle` inside the atomic block, after products:

```python
            variants = self._import_variants_and_prices(data)
            self.stdout.write(f"variants: {variants}")
```

Add the methods:

```python
    def _import_variants_and_prices(self, data) -> int:
        meta_all = data["meta"]
        ngn = Currency.objects.get(code="NGN")

        term_names = {
            (t["taxonomy"], t["slug"]): t["name"]
            for t in data["terms"]
            if t["taxonomy"].startswith("pa_")
        }
        variations_by_parent: dict[int, list[dict]] = {}
        for v in data["variations"]:
            variations_by_parent.setdefault(v["post_parent"], []).append(v)

        products_by_wp_id = {
            p.legacy_wp_id: p for p in Product.objects.filter(legacy_source=LEGACY_SOURCE)
        }

        count = 0
        for row in data["products"]:
            wp_id = row["ID"]
            product = products_by_wp_id.get(wp_id)
            if product is None:
                continue
            children = variations_by_parent.get(wp_id, [])

            if children:
                for position, child in enumerate(children):
                    cmeta = meta_all.get(str(child["ID"]), {})
                    attrs = {k: v for k, v in cmeta.items() if k.startswith("attribute_")}
                    variant = self._upsert_variant(
                        product=product,
                        sku=generate_sku(cmeta.get("_sku"), child["ID"]),
                        name=child["post_title"].split(" - ")[-1],
                        option_values=parse_option_values(attrs, term_names),
                        is_default=(position == 0),
                        position=position,
                    )
                    self._rewrite_prices(variant, cmeta, ngn)
                    count += 1
            else:
                pmeta = meta_all.get(str(wp_id), {})
                variant = self._upsert_variant(
                    product=product,
                    sku=generate_sku(pmeta.get("_sku"), wp_id),
                    name="Default",
                    option_values={},
                    is_default=True,
                    position=0,
                )
                self._rewrite_prices(variant, pmeta, ngn)
                count += 1
        return count

    @staticmethod
    def _upsert_variant(*, product, sku, name, option_values, is_default, position):
        variant, _ = ProductVariant.objects.update_or_create(
            sku=sku,
            defaults={
                "product": product,
                "name": name,
                "option_values": option_values,
                "is_default": is_default,
                "position": position,
            },
        )
        return variant

    def _rewrite_prices(self, variant, meta, currency) -> None:
        """Delete-and-recreate, NOT update-or-skip.

        The unique constraint is (variant, currency, country, starts_at); Postgres
        treats NULL starts_at as distinct, so update-or-skip would stack a fresh
        base price on every run without ever raising.
        """
        regular = self._decimal(meta.get("_regular_price"))
        if regular is None:
            return

        variant.prices.filter(currency=currency, country__isnull=True).delete()
        Price.objects.create(variant=variant, currency=currency, amount=regular)

        sale = self._decimal(meta.get("_sale_price"))
        if sale is None:
            return
        Price.objects.create(
            variant=variant,
            currency=currency,
            amount=sale,
            compare_at_amount=regular,
            starts_at=self._epoch(meta.get("_sale_price_dates_from")),
            ends_at=self._epoch(meta.get("_sale_price_dates_to")),
        )

    @staticmethod
    def _decimal(raw):
        if raw is None or str(raw).strip() == "":
            return None
        try:
            return Decimal(str(raw)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _epoch(raw):
        if not raw or not str(raw).strip().isdigit():
            return None
        return datetime.fromtimestamp(int(raw), tz=dt_timezone.utc)
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp/tests/test_import_catalog.py -v
```

Expected: 16 passed

- [ ] **Step 5: Commit**

```bash
git add backend/apps/migration_wp
git commit -m "feat(migration): variants keyed on variation id, prices delete-and-recreate"
```

---

## Task 11: Import stock, with the clobber guard

**Files:**
- Modify: `backend/apps/migration_wp/management/commands/import_catalog.py`
- Create: `backend/apps/migration_wp/tests/test_idempotency.py`

- [ ] **Step 1: Write the failing tests**

`backend/apps/migration_wp/tests/test_idempotency.py`:

```python
import pytest
from django.core.management import call_command

from apps.catalog.models import Product, ProductVariant
from apps.inventory.models import StockItem, StockMovement, Warehouse

pytestmark = pytest.mark.django_db

PLACEHOLDER = 100


@pytest.fixture
def lagos(db):
    return Warehouse.objects.get_or_create(
        name="Lagos HQ", defaults={"location_country": "NG"}
    )[0]


def test_instock_seeds_placeholder_and_outofstock_seeds_zero(artifact_path, lagos):
    call_command("import_catalog", str(artifact_path), "--skip-media")

    in_stock = StockItem.objects.get(variant__sku="TC-WP-101", warehouse=lagos)
    assert in_stock.quantity == PLACEHOLDER

    out = StockItem.objects.get(variant__sku="TC-WP-105", warehouse=lagos)
    assert out.quantity == 0


def test_stock_movement_recorded_for_audit(artifact_path, lagos):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    item = StockItem.objects.get(variant__sku="TC-WP-101", warehouse=lagos)
    assert item.movements.filter(reason="migration").exists()


def test_rerun_does_not_duplicate_products_or_variants(artifact_path, lagos):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    call_command("import_catalog", str(artifact_path), "--skip-media")

    assert Product.objects.filter(legacy_source="wp_ng").count() == 6
    assert ProductVariant.objects.count() == 7  # 5 simple + 2 variations
    assert StockItem.objects.filter(variant__sku="TC-WP-101").count() == 1


def test_rerun_does_not_clobber_hand_edited_stock(artifact_path, lagos):
    """THE CLOBBER TRAP. Hammed's team enters real counts before launch; the
    Plan-27 cutover re-run must not reset them to the placeholder."""
    call_command("import_catalog", str(artifact_path), "--skip-media")

    item = StockItem.objects.get(variant__sku="TC-WP-101", warehouse=lagos)
    item.quantity = 7
    item.save(update_fields=["quantity"])
    StockMovement.objects.create(stock_item=item, delta_quantity=-93, reason="adjustment")

    call_command("import_catalog", str(artifact_path), "--skip-media")

    item.refresh_from_db()
    assert item.quantity == 7, "migration overwrote a hand-entered stock count"


def test_force_stock_overrides_the_guard(artifact_path, lagos):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    item = StockItem.objects.get(variant__sku="TC-WP-101", warehouse=lagos)
    item.quantity = 7
    item.save(update_fields=["quantity"])
    StockMovement.objects.create(stock_item=item, delta_quantity=-93, reason="adjustment")

    call_command("import_catalog", str(artifact_path), "--skip-media", "--force-stock")

    item.refresh_from_db()
    assert item.quantity == PLACEHOLDER


def test_skip_stock_creates_no_stock_at_all(artifact_path, lagos):
    call_command("import_catalog", str(artifact_path), "--skip-media", "--skip-stock")
    assert StockItem.objects.count() == 0
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp/tests/test_idempotency.py -v
```

Expected: FAIL — `StockItem.DoesNotExist`

- [ ] **Step 3: Implement the stock phase**

Add imports to `import_catalog.py`:

```python
from apps.inventory.models import StockItem, StockMovement, Warehouse
```

Add a constant near `LEGACY_SOURCE`:

```python
PLACEHOLDER_STOCK = 100  # D2: real counts are entered by hand before launch
LAGOS = "Lagos HQ"
```

Add to `handle` inside the atomic block, after variants:

```python
            if options["skip_stock"]:
                self.stdout.write("stock: skipped (--skip-stock)")
            else:
                seeded, protected = self._import_stock(data, force=options["force_stock"])
                self.stdout.write(f"stock: {seeded} seeded, {protected} protected")
```

Add the method:

```python
    def _import_stock(self, data, *, force: bool) -> tuple[int, int]:
        """Seed Lagos HQ from _stock_status (D2).

        Refuses to touch any StockItem whose most recent movement was not a
        migration — i.e. one a human has adjusted. That is the load-bearing
        protection for the Plan-27 cutover re-run; --skip-stock is belt and braces.
        """
        warehouse, _ = Warehouse.objects.get_or_create(
            name=LAGOS, defaults={"location_country": "NG"}
        )
        meta_all = data["meta"]
        products_by_wp_id = {
            p.legacy_wp_id: p for p in Product.objects.filter(legacy_source=LEGACY_SOURCE)
        }

        seeded = protected = 0
        for row in data["products"]:
            product = products_by_wp_id.get(row["ID"])
            if product is None:
                continue
            status = (meta_all.get(str(row["ID"]), {}).get("_stock_status") or "").strip()
            quantity = PLACEHOLDER_STOCK if status == "instock" else 0

            for variant in product.variants.all():
                item = StockItem.objects.filter(variant=variant, warehouse=warehouse).first()
                if item is not None and not force and self._is_hand_edited(item):
                    protected += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"  protected {variant.sku}: qty {item.quantity} was edited by hand"
                        )
                    )
                    continue
                if item is None:
                    item = StockItem.objects.create(
                        variant=variant, warehouse=warehouse, quantity=quantity
                    )
                else:
                    item.quantity = quantity
                    item.save(update_fields=["quantity"])
                StockMovement.objects.create(
                    stock_item=item,
                    delta_quantity=quantity,
                    reason="migration",
                    note=f"Plan-21 seed from _stock_status={status or 'unset'}",
                )
                seeded += 1
        return seeded, protected

    @staticmethod
    def _is_hand_edited(item) -> bool:
        latest = item.movements.order_by("-created_at", "-id").first()
        return latest is not None and latest.reason != "migration"
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp/tests/test_idempotency.py -v
```

Expected: 6 passed

`StockMovement.REASONS` already includes `("migration", "Migration")` (verified in `apps/inventory/models.py`), so no model change is needed here.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/migration_wp
git commit -m "feat(migration): seed stock with a guard against clobbering hand-entered counts"
```

---

## Task 12: Import images to S3

**Files:**
- Modify: `backend/apps/migration_wp/management/commands/import_catalog.py`
- Modify: `backend/apps/migration_wp/tests/test_import_catalog.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/apps/migration_wp/tests/test_import_catalog.py`:

```python
from apps.catalog.models import ProductImage


def test_thumbnail_becomes_position_zero_image(artifact_path, uploads_root):
    call_command(
        "import_catalog", str(artifact_path), "--uploads-root", str(uploads_root)
    )
    p = Product.objects.get(slug="toke-scented-shea-butter")
    first = p.images.order_by("position").first()
    assert first.position == 0
    assert "toke-shea" in first.image.name


def test_gallery_and_acf_images_follow_the_thumbnail(artifact_path, uploads_root):
    call_command(
        "import_catalog", str(artifact_path), "--uploads-root", str(uploads_root)
    )
    p = Product.objects.get(slug="toke-scented-shea-butter")
    assert p.images.count() == 3  # thumbnail + 1 gallery + 1 ACF Small_Image_1


def test_missing_file_is_skipped_not_fatal(artifact_path, uploads_root):
    """toke-hair-food's attachment is deliberately absent from the fixture tree."""
    call_command(
        "import_catalog", str(artifact_path), "--uploads-root", str(uploads_root)
    )
    assert Product.objects.filter(slug="toke-hair-food").exists()
    assert Product.objects.get(slug="toke-hair-food").images.count() == 0


def test_images_do_not_duplicate_on_rerun(artifact_path, uploads_root):
    for _ in range(2):
        call_command(
            "import_catalog", str(artifact_path), "--uploads-root", str(uploads_root)
        )
    p = Product.objects.get(slug="toke-scented-shea-butter")
    assert p.images.count() == 3
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp/tests/test_import_catalog.py -k image -v
```

Expected: FAIL — image count 0

- [ ] **Step 3: Implement media import**

Add imports:

```python
from django.core.files.base import ContentFile

from apps.catalog.models import ProductImage
```

Add to `handle` inside the atomic block, after stock:

```python
            if options["skip_media"]:
                self.stdout.write("media: skipped (--skip-media)")
            else:
                copied, missing = self._import_media(data, Path(options["uploads_root"]))
                self.stdout.write(f"media: {copied} copied, {missing} missing")
```

Add the method:

```python
    ACF_IMAGE_KEYS = [f"Small_Image_{i}" for i in range(1, 5)] + [
        f"Medium_Image_{i}" for i in range(1, 3)
    ]

    def _import_media(self, data, uploads_root: Path) -> tuple[int, int]:
        """Copy referenced files from the read-only uploads mount to S3.

        De-duped by (product, source filename) so re-runs are free. A missing
        file is reported and skipped — never fatal.
        """
        attachments = data["attachments"]
        meta_all = data["meta"]
        products_by_wp_id = {
            p.legacy_wp_id: p for p in Product.objects.filter(legacy_source=LEGACY_SOURCE)
        }

        copied = missing = 0
        for row in data["products"]:
            product = products_by_wp_id.get(row["ID"])
            if product is None:
                continue
            meta = meta_all.get(str(row["ID"]), {})

            for position, att_id in enumerate(self._ordered_attachment_ids(meta)):
                rel = attachments.get(str(att_id))
                if not rel:
                    continue
                filename = Path(rel).name
                if product.images.filter(image__endswith=filename).exists():
                    continue

                source = uploads_root / rel
                if not source.exists():
                    missing += 1
                    self.stdout.write(
                        self.style.WARNING(f"  missing image {rel} for {product.slug}")
                    )
                    continue

                image = ProductImage(product=product, position=position, alt=product.name)
                image.image.save(
                    f"catalog/products/{product.slug}/{filename}",
                    ContentFile(source.read_bytes()),
                    save=True,
                )
                copied += 1
        return copied, missing

    def _ordered_attachment_ids(self, meta: dict) -> list[int]:
        """Thumbnail first, then gallery, then the ACF image slots."""
        ids: list[int] = []
        thumb = (meta.get("_thumbnail_id") or "").strip()
        if thumb.isdigit():
            ids.append(int(thumb))
        for part in (meta.get("_product_image_gallery") or "").split(","):
            if part.strip().isdigit():
                ids.append(int(part.strip()))
        for key in self.ACF_IMAGE_KEYS:
            val = (meta.get(key) or "").strip()
            if val.isdigit():
                ids.append(int(val))
        seen: set[int] = set()
        return [i for i in ids if not (i in seen or seen.add(i))]
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp -v
```

Expected: 26 passed, 3 skipped

- [ ] **Step 5: Commit**

```bash
git add backend/apps/migration_wp
git commit -m "feat(migration): copy product media to S3, missing files reported not fatal"
```

---

## Task 13: verify_catalog and the worklists

**Files:**
- Create: `backend/apps/migration_wp/management/commands/verify_catalog.py`
- Create: `backend/apps/migration_wp/tests/test_verify_catalog.py`

- [ ] **Step 1: Write the failing test**

`backend/apps/migration_wp/tests/test_verify_catalog.py`:

```python
import csv

import pytest
from django.core.management import call_command

from apps.catalog.models import Product

pytestmark = pytest.mark.django_db


def test_verify_reports_counts_and_writes_worklists(artifact_path, tmp_path, capsys):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    call_command("verify_catalog", str(artifact_path), "--out-dir", str(tmp_path))

    out = capsys.readouterr().out
    assert "products" in out

    pricing = tmp_path / "pricing-todo.csv"
    rows = list(csv.DictReader(pricing.open(encoding="utf-8")))
    assert len(rows) == 7  # one per variant
    assert {"sku", "product", "ngn_price", "gbp", "usd", "cad"} <= set(rows[0].keys())

    stock = tmp_path / "stock-todo.csv"
    assert stock.exists()

    review = tmp_path / "description-review.csv"
    assert review.exists()


def test_verify_flags_orphans(artifact_path, tmp_path, capsys):
    """A product removed from WordPress between runs must be reported, because
    update-or-skip never deletes."""
    call_command("import_catalog", str(artifact_path), "--skip-media")
    Product.objects.create(
        name="Ghost", slug="ghost", legacy_source="wp_ng", legacy_wp_id=999
    )
    call_command("verify_catalog", str(artifact_path), "--out-dir", str(tmp_path))

    assert "ghost" in capsys.readouterr().out


def test_verify_asserts_no_wp_content_urls(artifact_path, tmp_path, capsys):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    p = Product.objects.get(slug="toke-coconut-oil")
    p.description = '<img src="https://tokecosmetics.com/wp-content/uploads/x.jpg">'
    p.save(update_fields=["description"])

    call_command("verify_catalog", str(artifact_path), "--out-dir", str(tmp_path))

    assert "wp-content" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd backend && .venv/Scripts/python.exe -m pytest apps/migration_wp/tests/test_verify_catalog.py -v
```

Expected: FAIL — `Unknown command: 'verify_catalog'`

- [ ] **Step 3: Write the command**

```python
"""Post-import verification and the manual worklists Hammed's team needs."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.catalog.models import Category, Product, ProductImage, ProductVariant
from apps.pricing.models import Price

LEGACY_SOURCE = "wp_ng"


class Command(BaseCommand):
    help = "Verify an import and emit the pricing/stock/description worklists."

    def add_arguments(self, parser):
        parser.add_argument("artifact")
        parser.add_argument("--out-dir", default="docs/migration")

    def handle(self, *args, **options):
        data = json.loads(Path(options["artifact"]).read_text(encoding="utf-8"))
        out_dir = Path(options["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)

        self._counts(data)
        self._orphans(data)
        self._wp_content_scan()
        self._samples()
        self._pricing_todo(out_dir)
        self._stock_todo(out_dir)
        self._description_review(out_dir)

        self.stdout.write(self.style.SUCCESS(f"Worklists written to {out_dir}"))

    def _counts(self, data) -> None:
        src_products = len(data["products"])
        src_cats = len([t for t in data["terms"] if t["taxonomy"] == "product_cat"])
        self.stdout.write("--- counts (source -> dest) ---")
        self.stdout.write(
            f"products:   {src_products} -> "
            f"{Product.objects.filter(legacy_source=LEGACY_SOURCE).count()}"
        )
        self.stdout.write(f"categories: {src_cats} -> {Category.objects.count()}")
        self.stdout.write(
            f"variants:   {len(data['variations'])} variations -> "
            f"{ProductVariant.objects.count()} variants"
        )
        self.stdout.write(f"prices:     {Price.objects.count()}")
        self.stdout.write(f"images:     {ProductImage.objects.count()}")

    def _orphans(self, data) -> None:
        """Dest records with no source. update_or_create never deletes, so a
        product unpublished in WP between runs would otherwise live forever."""
        source_ids = {p["ID"] for p in data["products"]}
        orphans = Product.objects.filter(legacy_source=LEGACY_SOURCE).exclude(
            legacy_wp_id__in=source_ids
        )
        self.stdout.write("--- orphans (in platform, not in source) ---")
        if not orphans.exists():
            self.stdout.write("  none")
        for p in orphans:
            self.stdout.write(self.style.WARNING(f"  {p.slug} (legacy_wp_id={p.legacy_wp_id})"))

    def _wp_content_scan(self) -> None:
        """Currently zero occurrences. Kept as a guard: a re-export at cutover
        could pick up newly edited content with embedded WP asset URLs, which
        would 404 the moment DNS moves."""
        hits = Product.objects.filter(description__contains="wp-content") | (
            Product.objects.filter(short_description__contains="wp-content")
        )
        self.stdout.write("--- wp-content URL scan ---")
        if not hits.exists():
            self.stdout.write("  clean: 0 occurrences")
        for p in hits.distinct():
            self.stdout.write(self.style.ERROR(f"  wp-content reference in {p.slug}"))

    def _samples(self) -> None:
        self.stdout.write("--- 5 sample products ---")
        for p in Product.objects.filter(legacy_source=LEGACY_SOURCE).order_by("?")[:5]:
            variant = p.variants.first()
            price = variant.prices.filter(starts_at=None).first() if variant else None
            self.stdout.write(
                f"  {p.name} | {p.slug} | {price.amount if price else '-'} "
                f"| variants={p.variants.count()} | images={p.images.count()}"
            )

    def _pricing_todo(self, out_dir: Path) -> None:
        """GBP/USD/CAD are not derivable from the NG database and the intl store
        has no SKUs to match on — every variant needs manual entry."""
        with (out_dir / "pricing-todo.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["sku", "product", "ngn_price", "gbp", "usd", "cad"])
            for v in ProductVariant.objects.select_related("product").order_by("sku"):
                base = v.prices.filter(starts_at=None).first()
                w.writerow([v.sku, v.product.name, base.amount if base else "", "", "", ""])

    def _stock_todo(self, out_dir: Path) -> None:
        with (out_dir / "stock-todo.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["sku", "product", "warehouse", "seeded_qty", "real_qty"])
            for v in ProductVariant.objects.select_related("product").order_by("sku"):
                for item in v.stock_items.select_related("warehouse"):
                    w.writerow(
                        [v.sku, v.product.name, item.warehouse.name, item.quantity, ""]
                    )

    def _description_review(self, out_dir: Path) -> None:
        """ingredients/directions/warnings have no source field — this is the
        copywriting worklist, not a bug report."""
        with (out_dir / "description-review.csv").open(
            "w", newline="", encoding="utf-8"
        ) as fh:
            w = csv.writer(fh)
            w.writerow(
                ["slug", "product", "description_chars", "ingredients", "directions", "warnings"]
            )
            for p in Product.objects.filter(legacy_source=LEGACY_SOURCE).order_by("slug"):
                w.writerow(
                    [
                        p.slug,
                        p.name,
                        len(p.description),
                        "OK" if p.ingredients else "MISSING",
                        "OK" if p.directions else "MISSING",
                        "OK" if p.warnings else "MISSING",
                    ]
                )
```

- [ ] **Step 4: Run the full suite**

```bash
cd backend && .venv/Scripts/python.exe -m pytest -q --no-header
```

Expected: 579 passed, 3 skipped (550 baseline + 29 new)

- [ ] **Step 5: Commit**

```bash
git add backend/apps/migration_wp
git commit -m "feat(migration): verify_catalog with orphan detection and worklists"
```

---

## Task 14: Infrastructure — mount, grant, runbook

> **CORRECTION 2026-07-26, applied during execution.** Two assumptions below were
> wrong against the real box, and Tasks 15–16 inherit the fixes:
> - **`WP_DB_HOST=172.17.0.1` cannot work.** MariaDB binds `127.0.0.1` only
>   (`/etc/my.cnf:47`). The container reaches it through a read-only bind mount of
>   `/var/lib/mysql/mysql.sock` instead — passed per-invocation, never in compose,
>   so the long-lived containers hold no open path to the WordPress database.
>   `wp_reader` now treats a `WP_DB_HOST` starting with `/` as a socket path.
>   Rebinding MariaDB was rejected: it restarts the database behind the live store
>   and widens the listening surface on a box with `ufw` inactive.
>   (Bonus: the grant below is `@'localhost'`, which is exactly what a socket
>   connection authenticates as — over the bridge it would have needed `@'172.17.%'`
>   and would have failed auth even if the port had been open.)
> - **The checkout is at `/opt/tokecosmetics/repo`, not `/opt/tokecosmetics`.**
>   Every `cd /opt/tokecosmetics && docker compose -f infra/...` below is wrong.
>
> `docs/runbooks/migration.md` is the corrected, operational source of truth.
> Prefer it over the command text in this plan.

**Files:**
- Modify: `infra/docker-compose.prod.yml`
- Modify: `backend/apps/migration_wp/wp_reader.py` (unix socket support)
- Modify: `backend/apps/migration_wp/tests/test_wp_reader.py`
- Create: `docs/runbooks/migration.md`
- Modify: `docs/audit.md`

- [ ] **Step 1: Add the uploads mount and exports volume**

In `infra/docker-compose.prod.yml`, add to the `web` service's `volumes:` list:

```yaml
      - /home/tokecosm/public_html/wp-content/uploads:/mnt/wp-uploads-ng:ro
      - /opt/tokecosmetics/exports:/mnt/exports
```

The MariaDB socket is deliberately **not** added here — it is passed on the one-off
`run --rm` instead, so `web`/`worker`/`beat` never hold an open path to the
WordPress database between migrations.

Then create the exports directory owned by the container's uid. Letting Docker
autocreate the mount point leaves it `root:root` and every export fails on
permission:

```bash
ssh tokecosmetics 'install -d -o 10001 -g 10001 -m 755 /opt/tokecosmetics/exports'
```

- [ ] **Step 2: Create the scoped MySQL user on the VPS**

Generate a password and create the user. **Show Hammed this command before running it** — it is a write to the live database server.

The password is written straight to a `600` file and never printed: echoing it
would put a live credential into the session transcript, and every later command
reads it back with `set -a; . /root/wp-readonly.env; set +a`.

```bash
ssh tokecosmetics 'PW=$(openssl rand -base64 24); umask 077; printf "WP_DB_PASSWORD=%s\n" "$PW" > /root/wp-readonly.env; mysql -e "
CREATE USER IF NOT EXISTS \"wp_readonly\"@\"localhost\" IDENTIFIED BY \"$PW\";
GRANT SELECT ON tokecosm_wp481.wp_posts TO \"wp_readonly\"@\"localhost\";
GRANT SELECT ON tokecosm_wp481.wp_postmeta TO \"wp_readonly\"@\"localhost\";
GRANT SELECT ON tokecosm_wp481.wp_terms TO \"wp_readonly\"@\"localhost\";
GRANT SELECT ON tokecosm_wp481.wp_term_taxonomy TO \"wp_readonly\"@\"localhost\";
GRANT SELECT ON tokecosm_wp481.wp_term_relationships TO \"wp_readonly\"@\"localhost\";
FLUSH PRIVILEGES;"; unset PW; echo "grant done, password in /root/wp-readonly.env"'
```

`@'localhost'` is correct **because** the connection arrives over the unix socket.
Do not change it to `@'172.17.%'`.

- [ ] **Step 3: Prove the grant is actually limited**

```bash
ssh tokecosmetics 'set -a; . /root/wp-readonly.env; set +a; mysql -u wp_readonly -p"$WP_DB_PASSWORD" tokecosm_wp481 -e "SELECT COUNT(*) FROM wp_users;"'
```

Expected: `ERROR 1142 (42000): SELECT command denied to user 'wp_readonly'@'localhost' for table 'wp_users'`

This is the check that makes the whole credential argument real. If it returns a count instead of an error, stop and fix the grant.

```bash
ssh tokecosmetics 'set -a; . /root/wp-readonly.env; set +a; mysql -u wp_readonly -p"$WP_DB_PASSWORD" tokecosm_wp481 -e "SELECT COUNT(*) FROM wp_posts WHERE post_type=\"product\";"'
```

Expected: **99** (all statuses; the extract itself takes only the 69 `publish` + 2 `draft`). Measured 2026-07-26 — the plan originally said 181, which was wrong.

- [ ] **Step 4: Write the runbook**

Create `docs/runbooks/migration.md`. **Superseded during execution:** the draft
that was inlined here assumed `WP_DB_HOST=172.17.0.1` and `cd /opt/tokecosmetics`,
and its `chown -R tokecosm:tokecosm /opt/tokecosmetics/exports` would have made
the exports directory unwritable by the container (uid 10001) on the very next
run. The file as written is the source of truth; read it there.

It must cover, in order: how the container reaches MariaDB and why not over TCP ·
creating the scoped reader and proving ERROR 1142 on `wp_users` · creating
`/opt/tokecosmetics/exports` owned by 10001 · extract · review + dry run · back up
then import · verify and hand over the worklists by copy · THE STOCK RULE ·
teardown after cutover.

- [ ] **Step 5: Correct docs/audit.md**

Add this block to the products section of `docs/audit.md`:

```markdown
> **CORRECTION 2026-07-25 (Plan-21).** Three claims above were inferences that
> direct SQL disproves:
> - **0** published products have non-empty `_elementor_data`. Elementor is active
>   for site pages, not products. Descriptions are clean HTML (67/69 non-empty)
>   and port nearly verbatim — only `data-start`/`data-end` editor artifacts and
>   `&nbsp;` need stripping.
> - Ingredients/directions/warnings are **not** in the product body. They exist in
>   no field at all and must be written fresh.
> - Products carry ACF marketing fields this audit missed entirely:
>   `Benefits` (65/69), `product_main_usp` + `product_usp_1..4` (48/69),
>   `Testimonial_1..3_*` (47/69), `Small_Image_*`/`Medium_Image_*` (24/69, holding
>   attachment IDs). Values live under the key WITHOUT the leading underscore;
>   the `_`-prefixed twin holds only the ACF field key.
```

- [ ] **Step 6: Commit**

```bash
git add infra/docker-compose.prod.yml docs/runbooks/migration.md docs/audit.md
git commit -m "feat(infra): uploads mount + scoped wp_readonly grant, migration runbook"
```

---

## Task 15: Dry run against live data

**Files:** none — this is an operational task.

- [ ] **Step 1: Deploy the code to the VPS**

```bash
git tag backend-v0.2.0 && git push origin backend-v0.2.0
```

Watch the `deploy-backend` workflow to green.

- [ ] **Step 2: Extract**

Use section 2 of `docs/runbooks/migration.md` verbatim — socket transport, repo
path, and a password that never reaches the shell history:

```bash
ssh tokecosmetics 'cd /opt/tokecosmetics/repo && set -a && . /root/wp-readonly.env && set +a && docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod -f infra/docker-compose.prod.yml run --rm -v /var/lib/mysql/mysql.sock:/run/wp-mysql/mysql.sock:ro -e WP_DB_HOST=/run/wp-mysql/mysql.sock -e WP_DB_NAME=tokecosm_wp481 -e WP_DB_USER=wp_readonly -e WP_DB_PASSWORD web python manage.py extract_wp_catalog --out /mnt/exports/catalog-export.json'
```

Expected: `Wrote /mnt/exports/catalog-export.json: 71 products, 71 variations, 222 terms, ...` — 71 products = 69 publish + 2 draft; 222 terms = 40 product_cat + 137 product_tag + 45 pa_* attribute terms.

If the connection is refused, the socket mount is missing or MariaDB moved its
socket — confirm with `mysql -e "SHOW VARIABLES LIKE 'socket';"`. Do not fall back
to a TCP host; see the correction at the head of Task 14.

- [ ] **Step 3: Review the artifact before importing anything**

```bash
ssh tokecosmetics 'cd /opt/tokecosmetics && python3 -c "
import json; d=json.load(open(\"exports/catalog-export.json\"))
pub=[p for p in d[\"products\"] if p[\"post_status\"]==\"publish\"]
print(\"published:\", len(pub))
print(\"variations:\", len(d[\"variations\"]))
print(\"categories:\", len([t for t in d[\"terms\"] if t[\"taxonomy\"]==\"product_cat\"]))
print(\"attachments:\", len(d[\"attachments\"]))
print(\"sample:\", pub[0][\"post_title\"], \"|\", pub[0][\"slug\"])
"'
```

Expected: published 69, variations 71, categories 40.

- [ ] **Step 4: Dry run the import**

```bash
ssh tokecosmetics 'cd /opt/tokecosmetics/repo && docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod -f infra/docker-compose.prod.yml exec -T web python manage.py import_catalog /mnt/exports/catalog-export.json --dry-run'
```

Expected: `DRY RUN` banner, then counts. Confirm the production catalogue is still empty afterwards.

- [ ] **Step 5: Commit nothing; report the dry-run output to Hammed**

---

## Task 16: Real run and checkpoint

**Files:** none — operational.

- [ ] **Step 1: Back up Postgres first**

```bash
ssh tokecosmetics '/opt/tokecosmetics/repo/infra/deploy/backup.sh && ls -la /opt/tokecosmetics/backups/ | tail -3'
```

Expected: a fresh dump. Do not proceed without it.

- [ ] **Step 2: Run the import for real**

```bash
ssh tokecosmetics 'cd /opt/tokecosmetics/repo && docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod -f infra/docker-compose.prod.yml exec -T web python manage.py import_catalog /mnt/exports/catalog-export.json'
```

Expected: counts for categories, tags, products, variants, stock, media; missing-image warnings are acceptable and listed.

- [ ] **Step 3: Hand the worklists over — by copy, not by chown**

The exports directory belongs to uid 10001 because the container writes into it.
`chown -R tokecosm:tokecosm` (what this step originally said) would break the next
export with a permission error. Copy instead, to a directory outside `public_html`
— the worklists carry pricing columns and must not be web-served.

```bash
ssh tokecosmetics 'install -d -o tokecosm -g tokecosm -m 750 /home/tokecosm/migration-worklists && cp /opt/tokecosmetics/exports/*.csv /home/tokecosm/migration-worklists/ && chown tokecosm:tokecosm /home/tokecosm/migration-worklists/*.csv'
```

- [ ] **Step 4: Verify**

```bash
ssh tokecosmetics 'cd /opt/tokecosmetics/repo && docker compose -p tokecosmetics --env-file /opt/tokecosmetics/.env.prod -f infra/docker-compose.prod.yml exec -T web python manage.py verify_catalog /mnt/exports/catalog-export.json --out-dir /mnt/exports'
```

Expected: source→dest counts match, no orphans, `wp-content` scan clean, 5 samples printed.

- [ ] **Step 5: Confirm the storefront finally renders products**

This closes Plan-02 Task 10 Step 4, which has been blocked since 2026-07-25.

```bash
curl -s https://next.tokecosmetics.com/products | grep -c "product/"
```

Expected: greater than zero.

- [ ] **Step 6: Smoke-test search**

Search is Postgres trigram over the live table (`apps/search/backends.py` — `PostgresSearchBackend`), so there is **no index to rebuild**. Products become searchable the moment they are imported. Confirm:

```bash
curl -s "https://api.tokecosmetics.com/api/v1/search/?q=shea" | head -c 300
```

Expected: JSON with at least one result. If Meilisearch is switched on later (Plan-07b), this step gains a reindex.

- [ ] **Step 7: Checkpoint with Hammed**

Present: verify output, the three worklist CSVs, and 5 product pages side by side against their live WordPress equivalents. Then close the two items this plan unblocks — Plan-02 Task 10 Steps 4–5 and Task 11 Step 3 (drive a test-mode Paystack payment on a real order and confirm the webhook lands with `processed_at` set and `error=""`).

- [ ] **Step 8: Commit the worklists**

```bash
git add docs/migration/
git commit -m "docs(plan-21): migration worklists from the production run"
```

---

## Self-review notes (author)

**Spec coverage:** every spec section maps to a task — extract/import split (6, 8–12), scoped grant (14), field mapping (9, 10), idempotency table (10, 11), clobber trap (11), orphans + `wp-content` scan (13), worklists (13), audit.md correction (14), checkpoint (16). The one deliberate deviation (JSON fixture instead of a MySQL dump) is documented at the top with reasoning.

**Verified against the live code and database while writing this plan:**

- `StockMovement.REASONS` already includes `("migration", "Migration")` — no model change needed.
- `StockItem` related names are `stock_items` (from both variant and warehouse) and `movements`; `Price` is `prices`. The plan's queries use these.
- Search is Postgres trigram over the live table — there is no index to rebuild after import.
- Production currently has **0 categories, 0 tags, 0 products**, so the first import cannot hit a slug collision against pre-seeded data.
- `Lagos HQ` and `UK Warehouse` already exist; `NGN` and `NG` are seeded.

**Known soft spots for the implementer:**

1. ~~`WP_DB_HOST=172.17.0.1` in Task 15 assumes the default Docker bridge gateway.~~ **Confirmed broken 2026-07-26 and fixed** — MariaDB binds `127.0.0.1` only, the container uses a socket mount. See the correction at the head of Task 14.
2. ~~Task 15 Step 2's expected product count is 181 (publish + draft), while Step 3's published-only count is 69.~~ **The 181 was wrong.** Measured against the live DB 2026-07-26 with the scoped reader:

   | `post_type` | `post_status` | rows |
   |---|---|---|
   | product | publish | 69 |
   | product | importing | 27 |
   | product | draft | 2 |
   | product | private | 1 |
   | product_variation | publish | 71 |

   So `post_type='product'` (all statuses) = **99**, and the extract's `publish`+`draft` filter yields **71 products, 71 variations, 40 categories, 137 tags**. The 27 `importing` rows are a stalled WooCommerce importer's leftovers and are correctly excluded — but check none of them is a product you expect to see in the catalogue before signing off Task 16.

   This is the right database: 80 simple / 19 variable matches the audit's NG-current 79/20 (one product changed type since).
3. `Category.objects.update_or_create(legacy_wp_id=...)` would raise on a slug clash if a category with the same slug but no `legacy_wp_id` were ever created by hand. Not possible today (0 categories), but worth knowing if the import is ever re-run after manual category work.
