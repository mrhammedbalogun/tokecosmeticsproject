# docs/audit.md — Tokecosmetics WordPress Stores Audit (Plan-00)

> **Status:** Plan-00 audit. **Read-only** — no writes were made to any WordPress DB or file.
> **Audited:** 2026-07-14 by Claude, over `ssh tokecosmetics` (root socket auth to MariaDB 10.11.5).
> **How to re-run anything here:** `ssh tokecosmetics 'mysql -N -e "<SQL>"'`. Root has MariaDB socket auth, so no WP credentials are needed.
> Every claim below carries the SQL/command that produced it (verification requirement).

---

## 0. TL;DR — what changed vs the assumptions in master-tokerebuild.md §2

| Topic | Guide assumed | Audit found | Impact |
|---|---|---|---|
| **Old NG orders** (the big open question, item 2) | "check if pre-Nov-2025 orders exist" | **YES — 879 old NG orders, 2023-11-22 → 2025-11-16**, in a second prefix `wp8n_` inside the NG DB | Plan-23 order scope grows to **3 sources** |
| Order sources | 2 stores | **3 real order tables**: current NG (2,789), old NG (879), intl (119) | +879 orders to migrate |
| SKUs | products have `_sku` | **NG has 1 SKU total; intl has 0** | Every variant needs a generated SKU; SKU-matching impossible |
| Stock qty | migrate `_stock` levels | NG manages stock on **21** products; intl on **0** | Warehouse counts must be entered **manually** |
| UK warehouse seed (item 11) | seed from intl `_stock` by SKU match | **no intl SKUs, no intl stock qty** → cannot seed | Manual UK stock entry required |
| SEO plugin (item 7) | Yoast or RankMath | **neither** — no dedicated SEO plugin | New SEO layer (Plan-13) is a net-new build, not a port |
| Loyalty points | deferred (Plan-29) | **actively in use, real balances** (WPLoyalty 965 users + Points&Rewards 698 users) | Decision needed: preserve/honor balances? |
| Product content | in description/ACF | Marketing content (Benefits/USPs/Testimonials) in **ACF**; layout in **Elementor** | Descriptions need careful extraction (Elementor risk) |
| **Security** | cleaned 2026-06-17 | **`mah.php` malware dropper dated 2026-06-18** (day after cleanup) in `wholesale.tokecosmetics.com.ng` | Re-infection / missed file — needs removal decision |

**Three checkpoint confirmations needed from Hammed** are collected in §12.

---

## 1. Database & site topology

Four MariaDB databases exist. Two hold live WordPress stores; two are inert.

```sql
-- list databases
SHOW DATABASES;
-- prefixes within each store DB
SELECT SUBSTRING_INDEX(table_name,'_',1) AS pfx, COUNT(*)
FROM information_schema.tables WHERE table_schema='tokecosm_wp481' GROUP BY pfx;
```

| DB | Prefix | What it is | Live? |
|---|---|---|---|
| `tokecosm_wp481` | `wp_` | **Current NG store** — tokecosmetics.com, NGN, theme *blocksy-child* | ✅ live (docroot `public_html`) |
| `tokecosm_wp481` | `wp8n_` | **Old NG store** — tokecosmetics.com, NGN (pre-Nov-2025 rebuild) | ⚠️ DB-only; files replaced, `old.tokecosmetics.com` docroot is empty |
| `tokecosm_usawp100` | `wp8n_` | **Intl store** — tokecosmeticsintl.com, GBP, theme *woostify* | ✅ live (docroot `tokecosmeticsintl.com`) |
| `tokecosm_usawp100` | `wpstg0_` | WP-Staging clone of intl (44 orders, stale snapshot) | ❌ ignore |
| `tokecosm_wp788` | `wpsd_` | Near-empty WP (`/wp`, twentytwentyfive, 4 posts, no WooCommerce) | ❌ ignore |
| `tokecosm_tkdbn` | `wpzc_bookly_` | Leftover Bookly (appointments) tables, ~empty | ❌ ignore |
| `test` | — | 0 tables | ❌ empty |

**Only two docroots have a `wp-config.php`** (`public_html`, `tokecosmeticsintl.com`); all the vanity subdomains (base/uk/usa/canada/new/bulk/mg/wholesale) are parked/empty.

```bash
# docroots
ssh tokecosmetics "grep -riE 'DocumentRoot|ServerName' /usr/local/apps/apache2/etc/conf.d/webuzoVH.conf | sort -u"
# which have configs
for D in public_html tokecosmeticsintl.com old.tokecosmetics.com ...; do
  ssh tokecosmetics "grep -E 'DB_NAME|table_prefix' /home/tokecosm/$D/wp-config.php"; done
```

**Definitive order-table sweep (nothing hidden elsewhere):**
```sql
SELECT table_schema, table_name FROM information_schema.tables WHERE table_name LIKE '%wc_orders';
-- → only: usawp100.wp8n_ (intl), usawp100.wpstg0_ (staging clone),
--         wp481.wp8n_ (old NG), wp481.wp_ (current NG)
```

---

## 2. Verified counts (item 1)

Per store (`type='shop_order' AND status<>'trash'` for orders; `post_status='publish'` for products/coupons):

```sql
-- run per store with its DB + prefix
SELECT 'products_published', COUNT(*) FROM {DB}.{PFX}posts WHERE post_type='product' AND post_status='publish';
SELECT 'products_all',       COUNT(*) FROM {DB}.{PFX}posts WHERE post_type='product';
SELECT 'variations',         COUNT(*) FROM {DB}.{PFX}posts WHERE post_type='product_variation' AND post_status='publish';
SELECT 'product_cats',       COUNT(*) FROM {DB}.{PFX}term_taxonomy WHERE taxonomy='product_cat';
SELECT 'users',              COUNT(*) FROM {DB}.{PFX}users;
SELECT 'coupons',            COUNT(*) FROM {DB}.{PFX}posts WHERE post_type='shop_coupon' AND post_status='publish';
SELECT 'orders_nontrash',    COUNT(*) FROM {DB}.{PFX}wc_orders WHERE type='shop_order' AND status<>'trash';
SELECT 'reviews',            COUNT(*) FROM {DB}.{PFX}comments WHERE comment_type='review';
```

| Metric | NG current (`wp481.wp_`) | NG old (`wp481.wp8n_`) | Intl (`usawp100.wp8n_`) |
|---|---|---|---|
| Published products | 69 | 49 | 94 |
| All-status products | 99 | 52 | 94 |
| Variations | 81 | 69 | 2 |
| Product categories | 40 | 31 | 13 |
| Users | 1,218 | 300 | 51 |
| Coupons (published) | 5,288 | 8,008 | 46 |
| Orders (non-trash) | 2,789 | 879 | 119 |
| Reviews | 0 | 6 | 0 |

**Order status breakdown** (`GROUP BY status`):

| Status | NG current | NG old | Intl |
|---|---|---|---|
| on-hold | 1,440 | 717 | 83 |
| completed | 849 | 118 | 2 |
| processing | 2 | 1 | 18 |
| cancelled | 498 | 42 | 12 |
| pending | — | 1 | — |
| failed | — | — | 3 |
| refunded | — | — | 1 |

> **Note on "on-hold":** it's the single largest status in every store because bank-transfer (`bacs`) orders sit *on-hold* until payment is confirmed. This is the dominant NG payment flow — see §9.

**Media sizes** (`du -sh`): NG uploads **6.4 GB** (`/home/tokecosm/public_html/wp-content/uploads`); intl uploads **1.1 GB** (`/home/tokecosm/tokecosmeticsintl.com/wp-content/uploads`). Old NG media shares the NG uploads tree (WordPress stores by year/month, so 2023–2025 files coexist there).

---

## 3. Old NG orders — the archive found (item 2)

**Resolved: pre-Nov-2025 NG orders exist.** They live in `tokecosm_wp481.wp8n_wc_orders` (the old install left behind when NG was rebuilt onto a fresh `wp_` install ~Nov 2025).

```sql
SELECT COUNT(*), MIN(date_created_gmt), MAX(date_created_gmt)
FROM tokecosm_wp481.wp8n_wc_orders WHERE type='shop_order';   -- 879 · 2023-11-22 → 2025-11-16
-- identity proof:
SELECT option_value FROM tokecosm_wp481.wp8n_options WHERE option_name='siteurl';  -- https://tokecosmetics.com
SELECT currency, COUNT(*) FROM tokecosm_wp481.wp8n_wc_orders WHERE type='shop_order' GROUP BY currency; -- NGN 879
```

- Date ranges are contiguous with the current store (old ends 2025-11-16, new starts 2025-11-24) → clean handover, no overlap.
- All 879 are NGN → genuinely the old **NG** store, not a stray copy of the intl store (which is GBP).
- The old store also has **300 users** and **6 reviews** of its own.

**→ Plan-23 order scope = current NG (2,789) + old NG (879) + intl (119).** Migrate old NG orders with `source="legacy_ng_old"` (or similar) and `legacy_number="NGO-<id>"` to avoid colliding with current-NG legacy numbers.

---

## 4. Product shape (item 3)

**Types** (`taxonomy='product_type'`): NG current 79 simple / 20 variable; NG old 32/19; intl 93 simple / 1 variable.

**Attributes** (`taxonomy LIKE 'pa_%'`): `pa_product-size`, `pa_price-options`, `pa_size`, `pa_piece-pack`. These drive the variations. No `pa_shade`/`pa_color` — variation axis is mostly **size / pack**.

**Brands:** **no brand taxonomy exists** (`taxonomy LIKE '%brand%'` → 0 rows). Everything is own-brand "Toke Cosmetics". → In the new catalog, Brand is effectively a single value; don't expect to migrate a brand list.

**Custom fields (ACF):** products carry a rich ACF field set (all ~72 published+draft products):
```sql
SELECT pm.meta_key, COUNT(*) FROM tokecosm_wp481.wp_postmeta pm
JOIN tokecosm_wp481.wp_posts p ON p.ID=pm.post_id
WHERE p.post_type='product' AND pm.meta_key NOT LIKE '\_%'
GROUP BY pm.meta_key ORDER BY 2 DESC;
```
- **Portable structured content:** `Benefits`, `product_main_usp`, `product_usp_1..4`, `Medium_Image_1/2`, `Small_Image_1..4`, `details_image`, and embedded testimonials `Testimonial_{1..3}_{Customer_Name,Review_Text,Skin_Concern,Number_of_Item_Bought}`. → map USPs/benefits into Product fields; the ACF testimonials could seed the `reviews` app as pre-approved reviews (Hammed's call).
- **Ingredients / directions / warnings:** *not* present as dedicated ACF keys. They live in the **Elementor-built** product body (`elementor` + `elementor-pro` are active). ⚠️ **Migration risk:** `post_content` for products is likely Elementor JSON/shortcodes, not clean HTML — descriptions won't port verbatim. Plan-21 must render/extract these, and ingredients/directions/warnings may need manual entry into the new structured fields.

**Sample full products** (reproduce; not dumped here to keep this doc readable):
```sql
-- pick 3 ids then:
SELECT meta_key, meta_value FROM tokecosm_wp481.wp_postmeta WHERE post_id=%s;
-- keys of interest: _regular_price, _sale_price, _sale_price_dates_from/to, _sku, _stock,
--   _stock_status, _manage_stock, _weight, _thumbnail_id, _product_image_gallery, _product_attributes
```

---

## 5. Order shape / HPOS (item 4)

Both live stores run **HPOS** — orders in `{PFX}wc_orders` (+ `_wc_order_addresses`, `_wc_order_operational_data`, `_woocommerce_order_items`, `_woocommerce_order_itemmeta`), not `wp_posts`. Structure is standard WooCommerce HPOS; Plan-23's extraction SQL applies as written.

**Distinct payment methods** (`GROUP BY payment_method`):

| Store | Methods (count) |
|---|---|
| NG current | `bacs` Direct bank transfer (1,894), `paystack` (892), blank (3) |
| NG old | `bacs` (731), `paystack` (147), blank (1) |
| Intl | `bacs` (83), `rave`=Flutterwave (14), `stripe` incl. Apple/Google Pay (21 total), `paystack` (1) |

→ Confirms the exact gateway set Plan-09 builds: **Paystack, Flutterwave, Stripe (+Apple/Google Pay), PayPal, and bank transfer**. Bank transfer (`bacs`) is the *dominant* NG method — the new "awaiting payment confirmation" manual flow (Decision 3) is essential, not optional.

**Reproduce 3 full sample orders per store:**
```sql
SELECT * FROM {DB}.{PFX}wc_orders WHERE id=%s;
SELECT * FROM {DB}.{PFX}wc_order_addresses WHERE order_id=%s;
SELECT * FROM {DB}.{PFX}woocommerce_order_items WHERE order_id=%s;
SELECT meta_key, meta_value FROM {DB}.{PFX}woocommerce_order_itemmeta WHERE order_item_id=%s;
```

---

## 6. Customers & passwords (item 5)

**Password hash formats** (`SELECT LEFT(user_pass,4), COUNT(*) GROUP BY`):

| Store | `$wp$` (WP≥6.8 bcrypt) | `$P$` (phpass) | other |
|---|---|---|---|
| NG current | 1,218 | 0 | 0 |
| NG old | 216 | 84 | 0 |
| Intl | 49 | 2 | 0 |

→ **All hashes are migratable** — only `$wp$` and `$P$` formats, no plaintext/MD5/empty. The Plan-22 `WordPressPasswordHasher` (handles `$wp$`, `$P$`, `$2y$`) covers 100% of users. Old-password login will work for everyone.

**Customers with ≥1 order vs guest orders:**
```sql
SELECT COUNT(DISTINCT customer_id) FROM {DB}.{PFX}wc_orders WHERE type='shop_order' AND status<>'trash' AND customer_id>0;
SELECT COUNT(DISTINCT billing_email) FROM {DB}.{PFX}wc_orders WHERE type='shop_order' AND status<>'trash' AND customer_id=0 AND billing_email<>'';
```

| Store | Registered customers w/ orders | Distinct guest-order emails |
|---|---|---|
| NG current | 639 | 1,608 |
| NG old | 285 | 368 |
| Intl | 13 | 66 |

- **Migrate-with-account scope (Plan-22):** ~**937** registered customers-with-orders **before** cross-store email dedup (many old-NG customers likely re-registered on current NG). Expect the deduped number to be lower.
- **~2,042 distinct guest-order emails** across stores — these keep their email on the order (no account) and convert organically later (Decision 7 / Plan-11).
- **`tokecosmetics_customers.csv`** in the project root has 1 header + data rows of NG-centric customers (name/email/phone/state/city/address/country/products/#orders). It's a *derived export* (human-readable "Products Bought" strings, mixed NG/US rows, some malformed phone values shown in scientific notation from Excel). Treat `wp_users` + `wc_orders` as the source of truth; use the CSV only as a cross-check, not an import source.

---

## 7. Coupons (item 6)

```sql
SELECT 'total', COUNT(*) FROM {DB}.{PFX}posts WHERE post_type='shop_coupon' AND post_status='publish';
SELECT 'ever_used', COUNT(DISTINCT p.ID) FROM {DB}.{PFX}posts p JOIN {DB}.{PFX}postmeta m ON m.post_id=p.ID
  WHERE p.post_type='shop_coupon' AND m.meta_key='usage_count' AND CAST(m.meta_value AS UNSIGNED)>0;
SELECT 'unexpired', COUNT(*) FROM {DB}.{PFX}posts p WHERE p.post_type='shop_coupon' AND p.post_status='publish'
  AND p.ID NOT IN (SELECT post_id FROM {DB}.{PFX}postmeta WHERE meta_key='date_expires' AND meta_value<>'' AND CAST(meta_value AS UNSIGNED) < UNIX_TIMESTAMP());
```

| Store | Total | Ever used | Unexpired |
|---|---|---|---|
| NG current | 5,288 | **51** | 429 |
| NG old | 8,008 | **53** | 6 |
| Intl | 46 | 7 | 1 |

→ ~13,340 coupons exist but only **~111 were ever used** → overwhelmingly bulk auto-generated (the `woo-coupon-usage` + loyalty plugins generate per-customer codes). Historical orders snapshot their coupon **code** in the order lines, so used-but-expired coupons **don't** need migrating as entities.

**Recommended migrate list:** only **currently-active + unexpired** coupons (≈436), and even those should be reviewed for bulk patterns — the 429 "unexpired" on NG current are very likely mostly per-customer generated. Suggest: migrate hand-made marketing codes only (short, memorable codes); drop the generated ones. **→ Checkpoint confirm (a).**

---

## 8. SEO config (item 7)

```sql
SELECT option_name, option_value FROM {DB}.{PFX}options
WHERE option_name IN ('permalink_structure','woocommerce_permalinks');
-- SEO plugin markers:
SELECT COUNT(*) FROM {DB}.{PFX}options WHERE option_name LIKE 'wpseo%' OR option_name LIKE 'rank_math%';
```

- **Permalinks:** both stores use `/%postname%/`.
- **WooCommerce bases:** `product_base = /product`, `category_base = /product-categ…` (`/product-category`). → confirms Plan-24 redirect patterns: `/product/<slug>/ → /product/<slug>` and `/product-category/<slug>/ → /category/<slug>`.
- **No dedicated SEO plugin** — neither Yoast nor RankMath (0 marker options; not in active_plugins). SEO is currently theme-default + **Google Site Kit** / **Google Listings & Ads** only. → The Plan-13 enterprise SEO layer is a **net-new build**, not a port; there are no per-page SEO title/description overrides to migrate. Product/category/page URL lists for the redirect map come straight from `post_name` + the bases above.

---

## 9. Plugins → features to replicate (item 8)

```sql
SELECT option_value FROM {DB}.{PFX}options WHERE option_name='active_plugins';
```

**NG current — feature-bearing plugins:**
| Plugin | Feature | New-build home |
|---|---|---|
| `woo-paystack` | Paystack gateway | Plan-09 |
| `points-and-rewards-for-woocommerce` **and** `wployalty` | **TWO loyalty/points systems (in use — see §11)** | Plan-29 (deferred) — **balances at risk** |
| `woo-cart-abandonment-recovery` | Abandoned cart | Plan-30 (deferred) |
| `klaviyo` | Email marketing | Plan-30 |
| `reviewx` | Product reviews | Plan-11 reviews |
| `ajax-search-for-woocommerce-premium` | Product search | Plan-07 (Meilisearch) |
| `flexible-shipping-dhl-express`, `woocommerce-dhlexpress-services` | DHL rates | Plan-32 (deferred) |
| `woocommerce-shipping-local-pickup-plus` | Local pickup | Plan-08 delivery options |
| `advanced-custom-fields` | Product custom content | Plan-21 migration (see §4) |
| `product-recommendation-quiz-for-ecommerce` | Skin quiz | *not in MVP scope — flag* |
| `woocommerce-erprev` | ERPNext accounting bridge | context for Plan-28 accounting |
| `duracelltomi-google-tag-manager`, `official-facebook-pixel`, `pixelyoursite`, `tiktok-for-woocommerce`, `google-site-kit`, `google-listings-and-ads` | Marketing pixels/feeds | Plan-25 analytics tags |
| ⚠️ `wp-file-manager` | file manager | **known RCE vector — still active; security risk (see §12)** |
| `code-snippets` / `code-snippets-pro` | custom PHP snippets | **review for hidden business logic before decommissioning** |

**Intl — feature-bearing plugins:** `rave-woocommerce-payment-gateway` (Flutterwave), `woocommerce-paypal-payments` (PayPal), `woo-currency` (**multi-currency switcher** — the intl currency plugin), `buy-now-woo` + `fast-cart` (**Buy Now / express checkout — matches Decision 14**), `woostify-pro` theme.

---

## 10. Shipping zones/methods (item 10)

```sql
SELECT z.zone_id, z.zone_name, m.method_id, m.is_enabled
FROM {DB}.{PFX}woocommerce_shipping_zones z
LEFT JOIN {DB}.{PFX}woocommerce_shipping_zone_methods m ON z.zone_id=m.zone_id;
```

- **NG:** Zone *Lagos* = **17 `flat_rate` methods** (+ a `whooshing_shipping` method) — i.e. many per-area Lagos rates; Zone *Other States Nigeria* = `whooshing_shipping` + `flat_rate`. The many Lagos flat rates are exactly the **LGA-level granularity** Decision 13's region-based delivery is designed for.
- **Intl:** Zone *USA Locations* = `local_pickup`; Zone *UK* = `free_shipping`. **No configured worldwide/Rest-of-World paid zone** — intl shipping today is essentially UK-free + USA-pickup.
- The actual rate **amounts/titles** live in `wp_options` as `woocommerce_{method}_{instance}_settings` (serialized). These get extracted when seeding Plan-08 delivery options. **The intl rate table is thin → the Rest-of-World zone (Decision on ZZ) has little existing basis and will need Hammed to set real worldwide prices. → Checkpoint confirm (c).**

---

## 11. Inventory & the UK-warehouse problem (item 11)

```sql
SELECT COUNT(*) FROM {DB}.{PFX}postmeta WHERE meta_key='_sku' AND meta_value<>'';               -- SKUs
SELECT meta_value, COUNT(*) FROM {DB}.{PFX}postmeta WHERE meta_key='_stock_status' GROUP BY meta_value;
SELECT COUNT(*) FROM {DB}.{PFX}postmeta WHERE meta_key='_manage_stock' AND meta_value='yes';     -- managed
```

| | NG current | Intl |
|---|---|---|
| Products with a non-empty SKU | **1** | **0** |
| Products managing stock qty (`_manage_stock=yes`) | **21** | **0** |
| `_stock_status` | instock 172 / outofstock 9 | instock 93 / outofstock 3 |

**Consequences:**
1. **SKUs must be generated** for essentially every variant (Plan-21's `TC-WP-<id>` fallback becomes the *primary* path, not an edge case).
2. **Real stock quantities barely exist** — NG tracks 21 products, intl none. Migrating `_stock` yields almost nothing meaningful; products currently sell on in/out-of-stock **status** only.
3. **UK warehouse cannot be seeded from intl data** (Plan-21 item 3 assumption fails): intl has **no SKUs to match on and no stock quantities**. → Lagos HQ and UK warehouse stock counts must be **entered manually** by Hammed's team before launch. The migration can set every migrated product's initial stock to a placeholder (e.g. 0 or a large number) and produce a "stock to enter" checklist.

**Loyalty points balances (from §9 — real data):**
```sql
SELECT table_name, table_rows FROM information_schema.tables
WHERE table_schema='tokecosm_wp481' AND (table_name LIKE '%wlr%' OR table_name LIKE '%point%');
SELECT meta_key, COUNT(*) FROM tokecosm_wp481.wp_usermeta
WHERE meta_key LIKE '%point%' OR meta_key LIKE '%wlr%' GROUP BY meta_key;
```
- **WPLoyalty:** `wp_wlr_users` 965, `wp_wlr_points_ledger` 868, `wp_wlr_logs` 1,703, `wp_wlr_user_rewards` 15.
- **Points & Rewards:** `wps_wpr_points` / `points_details` 698 users, `wps_wpr_overall__accumulated_points` 567.
- Loyalty is **deferred to Plan-29**, but **customers hold real point balances now.** Recommend snapshotting both ledgers to CSV during migration so balances can be credited when Plan-29 ships, even though the feature isn't in the MVP. **→ Checkpoint decision.**

---

## 12. Security incident — findings & actions (handled 2026-07-14)

The June cleanup did **not** fully hold: an active re-infection was present. Investigated read-only, then remediated proportionately (WordPress is being retired by this rebuild, so the fix is scoped to closing active doors, not full disinfection — Hammed's decision 2026-07-14). All actions backed up to `/root/ir-2026-07-14/` first (reversible).

**Malicious footprint found (small & specific):**
- **`mah.php`** — `wholesale.tokecosmetics.com.ng/mah.php`, 1,427 bytes, **mtime 2026-06-18 00:51** (day after the 2026-06-17 cleanup). Obfuscated self-deleting PHP dropper (`@unlink($_SERVER['SCRIPT_FILENAME'])` + hex-encoded remote URL fetch). → **backed up + removed.**
- **Two backdoor admin accounts** (random-suffix names, 0 orders each, created in the incident window):
  - NG `tokecosm_wp481.wp_users` ID **1072** `adm_0f20f4` (2026-06-19) → **locked** (capabilities emptied `a:0:{}`, password set unusable, session tokens deleted).
  - Intl `tokecosm_usawp100.wp8n_users` ID **72** `backup_9d0d54` (2026-06-16) → **locked** same way.

**Ruled out (not malicious):** hash-named `*.php` with `BVUNTAR2` marker + `bv_connector_*` = legit BlogVault; ~26k files with uniform 2026-06-18 06:03–06:41 mtimes = a full WordPress core+plugins reinstall (the cleanup response); 26 PHP files under `uploads/` = plugin "silence" `index.php` guards + Elementor/WDesignKit template files (no webshells in uploads); `canada.tokecosmetics.com/index.php` = benign 404 placeholder.

**Remaining legit admins after lock-down:** NG = `admin`, `hammed`, `tokecosmeticsdigital` (Hammed confirmed his — reset its password, created mid-incident); Intl = `hammed`, `tokecosmetics`.

**Deliberately NOT done (proportionate — WP being retired):** full disinfection, `wp-file-manager` deactivation (known RCE vector, still active — the likely entry point), and blanket admin password rotation. Recommended as optional quick follow-ups but not required given the platform replacement. Backups of removed/locked artifacts live in `/root/ir-2026-07-14/`.

---

## 13. Checkpoint decisions (Hammed, 2026-07-14)

- **(a) Coupons → START FRESH.** Migrate **no** coupons; create new ones in the new admin as needed. Historical orders keep their coupon code in the order snapshot regardless. (Plan-21/23: skip coupon-entity migration.)
- **(b) Older NG orders → CONFIRMED in scope.** 879 orders (2023-11 → 2025-11) from `tokecosm_wp481.wp8n_wc_orders` join Plan-23 as a third source (`source="legacy_ng_old"`, `legacy_number="NGO-<id>"`).
- **(c) Shipping** — NG = per-Lagos-area flat rates + "Other States"; intl = UK-free + USA-pickup, no worldwide paid zone → **Rest-of-World pricing set fresh** in admin (Plan-08).
- **(d) Loyalty points → DO NOT preserve.** Existing balances lapse; loyalty starts from zero at launch (Plan-29). No snapshot needed during migration.
- **(e) Manual stock entry → ACCEPTED.** No reliable WP stock data (NG 21 managed, intl 0). Lagos + UK warehouse counts entered by hand before launch; migration sets placeholder stock + emits a "counts to enter" checklist.
- **(f) Product descriptions** — Elementor-built; ingredients/directions/warnings likely need manual re-entry into structured fields (Plan-21). Accepted as a known migration cost.
- **(g) Security → proportionate remediation done** (see §12): malware removed, backdoors locked; no full WP disinfection since the platform is being replaced.

**→ Plan-00 CHECKPOINT PASSED. Proceed to Plan-01.**
```
