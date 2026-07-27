# Plan-21 — Product migration (WooCommerce → platform)

**Date:** 2026-07-25
**Status:** design approved by Hammed, pending spec review
**Branch:** `plan-21-migration-products`

## Objective

Move the NG catalogue — products, variants, categories, tags, prices, stock, images, and the ACF marketing content — from the live WooCommerce database into the new platform, so the production storefront at `next.tokecosmetics.com` shows real products for the first time.

This plan is the gate for three things currently stranded:

1. Plan-02 Task 10 Steps 4–5 (storefront renders products; one order walked end to end)
2. Plan-02 Task 11 Step 3 (a Paystack-originated webhook confirmed against a real order)
3. Launch itself — everything downstream needs a catalogue

International products are **not** migrated as separate entities. NG inventory is the source of truth (Hammed, 2026-07-12). Plan-23 needs no product linkage for intl-only order items because order items store snapshots.

## Verified source facts

Audited by direct SQL against `tokecosm_wp481` on 2026-07-25. Every number below was produced by a query run that day, not carried over from `docs/audit.md`.

| Fact | Value |
|---|---|
| Published products | 69 |
| Variable products / variations | 18 / 71 |
| Categories (`product_cat`) | 40, **all flat** (no parent links) |
| Product tags | 137 |
| Brand taxonomy | none — single brand |
| Products with a non-empty SKU | **1** |
| Duplicate slugs | **0** |
| Descriptions non-empty | 67 / 69 |
| Excerpts non-empty | 67 / 69 |
| Products with a main image | **69 / 69** |
| Products with a gallery | 6 |
| Price range (simple, published) | ₦500 – ₦107,500 across 51 products |
| Variation attribute axes | `pa_product-size` (55), `pa_price-options` (43), `pa_size` (12), `shea-variant` (4, non-taxonomy) |
| Products managing stock quantity | 21 |
| `_stock_status` | 172 instock / 9 outofstock |

### ACF content the Plan-00 audit did not catalogue

Values live under the key **without** the leading underscore; the `_`-prefixed twin holds only the ACF field key (`field_68e6…`) and must be ignored.

| Field | Filled |
|---|---|
| `Benefits` | 65 / 69 |
| `product_main_usp`, `product_usp_1..4` | 48 / 69 |
| `Testimonial_1..3_{Review_Text, Customer_Name, Skin_Concern, Number_of_Item_Bought}` | 47 / 69 |
| `Small_Image_1..4`, `Medium_Image_1..2` | 24 / 69 — **attachment IDs**, not URLs |

### Corrections to `docs/audit.md`

The audit recorded inferences that this plan's direct queries disprove. `audit.md` is updated as part of Task 1 so the next reader is not misled.

| audit.md claim | Reality |
|---|---|
| Product bodies are Elementor-built; descriptions "won't port verbatim" (line 150) | **0** published products have non-empty `_elementor_data`. Elementor is active for site pages, not products. Descriptions are clean HTML and port nearly verbatim. |
| Ingredients/directions/warnings live in the Elementor body and need manual re-entry | They exist in no field at all. What *does* exist is `Benefits`/USPs/testimonials, which the audit missed entirely. |
| Descriptions contain shortcodes | 1 product contains a `[` character; none contains a shortcode block. |

## Decisions

| # | Decision | Who / when |
|---|---|---|
| D1 | Descriptions migrate automatically with cleanup of `data-start`/`data-end` editor artifacts and `&nbsp;`; a review CSV lists all 69 for manual polish | Hammed, 2026-07-25 |
| D2 | Stock: `instock` → placeholder 100 at Lagos HQ, `outofstock` → 0. Real counts entered by hand before launch | Hammed, 2026-07-25 |
| D3 | Testimonials are preserved as testimonials in `Product.testimonials`, **never** as `Review` rows, and never touch `rating_avg`/`rating_count` | Hammed, 2026-07-25 |
| D4 | `Benefits` appends to `description` as a `<ul>`; USPs preserved in `Product.usps` for a later storefront plan | Hammed, 2026-07-25 |
| D5 | Extract/import split, both as Django management commands (Option D) | Hammed, 2026-07-25, after Fable 5 consult |

### D3 rationale — why testimonials must not become reviews

`storefront/src/lib/seo.ts:154-157` emits schema.org `aggregateRating` whenever `rating_count > 0`. The 47 testimonials carry **no rating value** in the source — only name, text, skin concern, and quantity bought. Importing them as `Review` rows would require inventing a rating, which would publish fabricated review snippets to Google. That risks a manual action against the domain on top of misleading customers. They are marketing testimonials and migrate as such.

## Architecture

Three Django management commands in a new `apps/migration_wp`. Both halves live in the image the tag-triggered deploy already builds, so both are covered by CI against a fixture dump.

```
extract_wp_catalog  →  catalog-export.json + media-manifest.json
        │                (reads MariaDB; credentials supplied per-invocation)
        ▼
import_catalog      →  Postgres + S3
        │                (never opens a MariaDB connection)
        ▼
verify_catalog      →  import-report.md, pricing-todo.csv,
                       stock-todo.csv, description-review.csv
```

**Why split.** The artifact is diffable, so a dry run is genuinely reviewable by Hammed before anything touches production. Import is deterministic and re-runnable from a fixed artifact. Re-running `extract` at cutover *is* the drift refresh, so staleness needs no separate mechanism.

**Why both stay Django commands.** A standalone host script would need its own Python environment on the VPS, untested by CI and unversioned by the deploy pipeline. Keeping both in `apps/migration_wp` means the fixture-dump tests cover the real code path.

### `wp_reader.py`

Thin functions returning plain dicts, one per query, no ORM. Uses `pymysql` (pure Python, no build step) and `phpserialize` for `_product_attributes` and gallery parsing. Broken serialisation is logged and skipped, never fatal.

Reads exactly five tables: `wp_posts`, `wp_postmeta`, `wp_terms`, `wp_term_taxonomy`, `wp_term_relationships`.

### Credential handling

A dedicated MariaDB user, created for the migration and dropped after cutover:

```sql
CREATE USER 'wp_readonly'@'localhost' IDENTIFIED BY '<generated>';
GRANT SELECT ON tokecosm_wp481.wp_posts             TO 'wp_readonly'@'localhost';
GRANT SELECT ON tokecosm_wp481.wp_postmeta          TO 'wp_readonly'@'localhost';
GRANT SELECT ON tokecosm_wp481.wp_terms             TO 'wp_readonly'@'localhost';
GRANT SELECT ON tokecosm_wp481.wp_term_taxonomy     TO 'wp_readonly'@'localhost';
GRANT SELECT ON tokecosm_wp481.wp_term_relationships TO 'wp_readonly'@'localhost';
```

This user **cannot read `wp_users`, `wp_usermeta`, or any order table**, so a compromise of the Django container cannot reach customer PII through it. Credentials are never written to `.env.prod`; they are passed per-invocation:

```bash
docker compose -p tokecosmetics -f infra/docker-compose.prod.yml \
  run --rm -e WP_DB_USER=wp_readonly -e WP_DB_PASSWORD=... \
  web python manage.py extract_wp_catalog --out /mnt/exports/catalog-export.json
```

The settings module reads `WP_DB_*` from the environment and defaults to unset; `import_catalog` and `verify_catalog` never reference them.

## Data mapping

### Categories → `Category`

`term_id` → new `Category.legacy_wp_id`. Slug preserved **exactly**. All 40 are flat, so `parent` is null throughout; the importer still honours `tt.parent` if a nested term appears at cutover. `tt.description` → `description`.

### Products → `Product`

| Source | Target | Notes |
|---|---|---|
| `post_title` | `name` | |
| `post_name` | `slug` | preserved exactly — SEO-critical, 0 duplicates confirmed |
| `post_content` | `description` | cleaned: strip `data-start`/`data-end`, collapse `&nbsp;` |
| `post_excerpt` | `short_description` | |
| `post_status` | `status` | `publish` → `active`, `draft` → `draft` |
| `post_date_gmt` | `published_at` | |
| `ID` | `legacy_wp_id` + `legacy_source="wp_ng"` | idempotency key |
| `product_cat` terms | `categories` | via `legacy_wp_id` |
| `product_tag` terms | `tags` | created on demand |
| `Benefits` | appended to `description` as `<ul>` | D4 |
| `product_main_usp`, `product_usp_1..4` | `Product.usps` (new JSON) | D4 |
| `Testimonial_*` | `Product.testimonials` (new JSON) | D3 |

`ingredients`, `directions`, `warnings` are left blank — no source field exists. They appear in `description-review.csv` for manual entry.

### Variants → `ProductVariant`

Simple product → one default variant, `is_default=True`, `sku = _sku or "TC-WP-<product_id>"`.

Variable product → one variant per variation, **`sku = _sku or "TC-WP-<variation_id>"`**. Keying on the variation's own post ID is mandatory: `ProductVariant` has no `legacy_wp_id`, so `sku` is the idempotency key, and using the parent ID would collide across all 71 variations.

`option_values` from the variation's `attribute_*` meta, resolving taxonomy slugs to term names where the axis is a `pa_*` taxonomy and using the raw value for the non-taxonomy `shea-variant`.

### Prices → `Price`

`_regular_price` → one NGN `Price`. `_sale_price` with a date window → a second NGN `Price` with `compare_at_amount` set to the regular price and `starts_at`/`ends_at` from `_sale_price_dates_*`.

GBP/USD/CAD are **not derivable** from this database, and the intl store cannot prefill them — it has no SKUs to match on. All 69 products land in `pricing-todo.csv` for the admin grid.

### Stock → `StockItem` + `StockMovement`

Per D2: `_stock_status='instock'` → quantity 100 at Lagos HQ, `outofstock` → 0. One `StockMovement(reason='migration')` per item for audit. Every product lands in `stock-todo.csv` with its WooCommerce status and the placeholder applied, for the manual count pass.

The UK warehouse is **not** seeded. The intl store has no SKUs and no stock quantities, so the master plan's SKU-match seeding is impossible. UK counts are entered by hand.

### Images → `ProductImage`

`_thumbnail_id` → position 0. `_product_image_gallery` → positions 1..n. `Small_Image_1..4` / `Medium_Image_1..2` are attachment IDs and append after the gallery.

Files are read from the read-only mount `/mnt/wp-uploads-ng` (added to `docker-compose.prod.yml` as `/home/tokecosm/public_html/wp-content/uploads:ro`), uploaded to S3 under `media/catalog/<product-slug>/<filename>`. De-duped by (product, source filename). Missing files are logged to a broken-image report and never abort the run.

## Idempotency and re-run policy

The migration runs at least three times: dry run, rehearsal, and the Plan-27 cutover run. Each object type needs an explicit key.

| Object | Key | Re-run behaviour |
|---|---|---|
| `Category` | `legacy_wp_id` | update in place |
| `Product` | `legacy_source` + `legacy_wp_id` | update in place |
| `ProductVariant` | `sku` (`TC-WP-<variation_id>`) | update in place |
| `Price` | — | **delete-and-recreate** all rows for the variant inside the run transaction |
| `ProductImage` | (product, source filename) | skip if present |
| `StockItem` | (variant, warehouse) | governed by `--skip-stock`, below |

`Price` cannot use update-or-skip: a regular + sale pair would duplicate on every run. The importer deletes the variant's existing NGN migration-sourced prices and recreates them atomically.

### The clobber trap

[`master-tokerebuild.md:1309`](../../../../master-tokerebuild.md) has Plan-27 cutover perform a "fresh full migration run against current live data."

- **Intl prices are safe.** Plan-27 sequences the run *before* Hammed's team enters GBP/USD/CAD prices.
- **Stock is not.** Real Lagos and UK counts are entered before launch (D2), and a fresh run would reset them to placeholders.

Two mechanisms, deliberately overlapping:

1. **Automatic guard (load-bearing).** `import_catalog` refuses to modify any `StockItem` whose most recent `StockMovement.reason` is not `migration` — i.e. anything a human has touched — and reports each one it skipped. Overriding requires an explicit `--force-stock`. Safety does not depend on anyone remembering a flag.
2. **`--skip-stock` (belt and braces).** Skips the stock phase wholesale. The Plan-27 runbook specifies it for any run after manual counts have been entered, so the intent is visible in the command itself rather than implied by the guard.

### Orphans

Update-or-skip never deletes. A product unpublished in WordPress between rehearsal and cutover would survive in Postgres forever. `verify_catalog` reports **dest records with no source** as a distinct section; the master plan's verification only counted source → dest.

## Error handling

- Broken PHP serialisation in `_product_attributes` or the gallery: log, skip that field, continue.
- Missing image file on disk: log to the broken-image report, continue.
- A product that fails entirely: recorded with its reason; the run continues and the report lists every published WP product as either migrated or explained. No published product is silently dropped.
- `import_catalog` runs inside a transaction per product, so a mid-run failure leaves no half-built product.
- `--dry-run` prints the full report and writes nothing — required before every real run.

## Testing

Fixture-based, no live database in CI:

- A trimmed MySQL fixture dump (~6 products covering simple, variable, sale-priced, missing-image, broken-serialisation, and full-ACF cases) committed under `apps/migration_wp/tests/fixtures/`.
- `wp_reader` unit tests against the fixture.
- Importer tests: idempotency (run twice, assert identical counts and no duplicate prices), SKU collision across variations, `--skip-stock` refusing to clobber a hand-edited `StockItem`, testimonials never producing `Review` rows or moving `rating_count`, slug preserved exactly.
- A `wp-content` assertion across all imported text columns — currently 0 occurrences, kept as a guard because re-export at cutover could pick up newly edited content.

## Verification and checkpoint

`verify_catalog` outputs:

- counts source vs dest for products, variants, categories, tags, prices, images
- every published WP product either migrated or listed with a reason
- dest-with-no-source orphans
- zero `wp-content` occurrences across text columns
- 5 random products printed side by side (name, slug, price, stock, image count)

**Checkpoint:** Hammed reviews the storefront with real products, spot-checks 5 product pages against the live WP equivalents, and receives `pricing-todo.csv` + `stock-todo.csv` + `description-review.csv`.

Immediately after sign-off, the two items this plan unblocks are closed: Plan-02 Task 10 Steps 4–5, and Task 11 Step 3 (Paystack webhook confirmed against a real order).

## Out of scope

- Storefront rendering of `usps` and `testimonials` — data is preserved; presentation is a later plan
- Customers (Plan-22), orders (Plan-23), SEO redirects (Plan-24)
- Intl products as separate entities
- Manual entry of stock counts, intl prices, ingredients/directions/warnings — this plan produces the worklists

## Open risks

1. **Placeholder stock of 100 is not real.** Between migration and manual entry, the storefront will accept orders for quantities that may not physically exist. Mitigated by the pre-launch count pass; the window is only dangerous if the site takes real traffic before then.
2. **Descriptions carry editor artifacts.** `data-start`/`data-end` attributes suggest paste-from-editor content. Cleanup is mechanical, but `description-review.csv` exists because 69 products is small enough to eyeball.
3. **`shea-variant` is not a taxonomy.** Four variations use a raw meta axis. Handled explicitly, but it is the most likely source of a wrong `option_values` label.
4. **The S3 backup credential risk remains parked.** The key writing nightly DB backups can also delete them, and bucket versioning is off. Hammed reviewed this on 2026-07-25 and chose to keep it parked until Plan-27. This plan writes catalogue data, which is re-derivable from WordPress, so the exposure stays bounded — but it stops being bounded when customer data lands in Plan-22/23, which is the point to fix it.
