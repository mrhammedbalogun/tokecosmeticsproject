# Plan-23 — order migration

Master spec: `master-tokerebuild.md` §Plan-23-migration-orders. Follows Plan-22, which
supplies the `LegacyIdentity` map this stage links orders through. The 23-table grant
approved for Plan-22 already covers everything here — no second approval.

> **One decision needed from Hammed** (§Decision, at the bottom): what to do with 2,277
> unpaid bank-transfer orders worth ₦34M+. Everything else is settled and buildable.

---

## Grounding (measured on the live host, 2026-08-01)

### It is 4,096 orders, not 879

`architecture.md:752` and `orders/views.py:284` both say **879 legacy orders**. That number
is real but it is only the **dead NG-old store**. The live NG store has 3,093 more.

| Store | Database · prefix | Orders | First | Last |
|---|---|---|---|---|
| NG current | `tokecosm_wp481.wp_` | **3,093** | 2025-11-24 | 2026-08-01 |
| NG old | `tokecosm_wp481.wp8n_` | **879** | 2023-11-22 | 2025-11-16 |
| Intl | `tokecosm_usawp100.wp8n_` | **124** (+13 in `posts`) | 2024-04-19 | 2026-07-31 |

**4,096 orders, 4.7× the number this project has been sizing against.** That matters most
for the expiry-sweep poison isolation (`architecture.md` §"The expiry sweep's poison
isolation"), whose whole argument was sized against 879 unknown-gateway orders.

### THE ONE THAT WOULD HAVE COST MONEY: `wc-on-hold` means the opposite of `on_hold`

| Store | `wc-on-hold` | of which PAID | Gross |
|---|---|---|---|
| NG current | 1,476 | **0** | ₦34,245,092.43 |
| NG old | 717 | **0** | (NGN) |
| Intl | 84 | **0** | (GBP/USD/CAD/NGN) |

**Every single one of the 2,277 `wc-on-hold` orders has `date_paid_gmt IS NULL`.** In this
WooCommerce, `wc-on-hold` is what the `bacs` gateway sets when a customer picks bank
transfer and has not paid — it means *no money*.

In the new system `on_hold` means the **opposite**: money in hand. `orders/services.py:41`
parks a **PAID** order there when a freight quote is cancelled and calls the balance "the
debt is live", and `analytics/queries.py:45` includes `on_hold` in `REVENUE_STATUSES`.

Mapping the word to the word would put **₦34.2M of never-collected money into the Plan-20
revenue dashboard on day one**, and drop 2,277 orders into the refunds-owed triage queue
as debts owed to customers who never paid. Nothing would raise. The dashboard would simply
be wrong, in the direction that flatters.

### Everything else measured

- **Guests are the majority: 2,840 of 4,096 (69%)** — NG 2,237/3,093, old 502/879, intl
  101/124. `architecture.md:1003-1010` requires these land `user=None` + real `email` or
  `claims.py` can never attach them.
- **26 order IDs collide between NG-old and intl.** Their ID ranges overlap (18412–28734
  vs 19039–21446) where NG-current's does not. No custom order-number plugin exists, so
  the WooCommerce ID *is* the customer-facing number.
- **Four currencies**: NGN, GBP, USD, CAD. Country ≠ store — the NG store holds 15 US/GB/CA
  orders and the intl store holds 18 NG ones.
- **Gateways**: `bacs` (2,141), `paystack` (1,037), `rave`/Flutterwave (15), `stripe` (21),
  3 blank. None of `bacs`/`rave` exist in the new payment registry.
- **NG states are WooCommerce codes**: LA 2,195, FC 102, OY 99, OG 96, ED 75 … plus **99
  NULL**. `Address` wants `core.Region` FKs.
- **Money**: NG-current tax ₦3,566,376.24, shipping ₦12,425,618.21, discounts ₦203,965.60.
- **Refunds: 1 in total** (intl, USD 187.00). Refund migration is a rounding error.
- **106 of 7,930 NG line items have no `_product_id`**, and orders reference 72 distinct
  products against 99 still in `wp_posts` (Plan-21 imported 71).
- **4 orders are cancelled-or-trashed but PAID** (₦154,181.98 total) — money moved, order
  ended.
- **10 `trash` orders** (8 NG, 2 intl).
- **2 NG `wc-processing` orders total ₦0.00.**

---

## Design rulings

### 1. The status map is written against `date_paid_gmt`, never against the status name

The WooCommerce status is a label; `date_paid_gmt` is the fact. Where they disagree the
payment date wins, and the order is flagged rather than silently reconciled.

| WooCommerce | n | → | Why |
|---|---|---|---|
| `wc-completed` (all paid) | 1,164 | `completed` | |
| `wc-processing` (all paid) | 21 | `processing` | |
| `wc-on-hold` (**all unpaid**) | 2,277 | **see Decision** | never `on_hold` |
| `wc-cancelled` unpaid | 616 | `cancelled` | |
| `wc-cancelled`/`trash` **paid** | 4 | `cancelled` + `review_reason` | money moved, order ended — a human must look |
| `wc-pending` | 1 | `expired` | |
| `wc-failed` | 3 | `expired` | |
| `wc-refunded` | 1 | `refunded` | the single real refund |
| `trash` unpaid | 6 | skipped, counted in the report | deleted in WooCommerce; importing them resurrects what someone chose to bin |

`needs_review` is a flag and never a status (`orders/models.py:31-38`), so the 4 paid-but-
cancelled orders keep `status="cancelled"` and carry the reason.

### 2. Order numbers are store-prefixed, because 26 of them collide

`Order.number` is globally unique and 26 IDs exist in both NG-old and intl. Numbering on
the bare WooCommerce ID would raise `IntegrityError` mid-import — or, with a careless
`get_or_create`, silently merge two unrelated customers' orders into one.

```
NG-16521   (legacy_ng,     wp id 16521)
OLD-28734  (legacy_ng_old, wp id 28734)
INT-21446  (legacy_intl,   wp id 21446)
```

`legacy_number` keeps the bare WooCommerce ID, which is what the customer has in their
inbox and what support will be asked about. Both are indexed already
(`orders/models.py:74-79`).

### 3. Linkage is `LegacyIdentity` first, `billing_email` for guests only

Plan-22 built the `(store, wp_user_id) → user` map for this. `billing_email` is the
fallback **only** when `customer_id = 0`, and then the order lands `user=None` with the
email stored, per `architecture.md:1003-1010` — never matched to an account by string.
Matching a registered order by email would attach an order to whoever holds that address
today, which is the exact attack `claims.py` was written to refuse.

### 4. A `legacy` gateway code, so 4,096 orders cannot poison the expiry sweep

`bacs` and `rave` do not exist in the payment registry, and `expire_pending_orders` raises
`UnknownGateway` on an unknown code. The per-order `try/except` added in Plan-09b means one
order no longer starves its siblings — but 4,096 orders raising every five minutes forever
is a log fire, not a fix.

Migrated orders therefore carry **`payment_method="legacy"`**, a code the registry knows
and the sweep skips, with the original WooCommerce gateway preserved verbatim in the
payment record for history. A migrated order is never a live payment attempt: there is
nothing to expire, capture or refund through a gateway that this platform never talked to.

### 5. An incomplete address skips the ADDRESS, never the order

NG states are WooCommerce codes and 99 are NULL. A `code → core.Region` map is built from
`core.Region`, and a row that cannot be resolved stores the raw address snapshot with
`region=None`. `Order.shipping_address`/`billing_address` are JSON snapshots, not FKs
(`orders/models.py:49-50`), so this costs nothing at order level — the region matters for
`Address` rows, which are Plan-22 leftovers and are not created here at all.

### 6. Line items keep what WooCommerce recorded, not what the catalogue says today

106 line items have no `_product_id`, and orders reference products that no longer exist.
`OrderItem` stores the name, SKU and price **as sold**, and links to a `ProductVariant`
only when Plan-21's `legacy_wp_id` map resolves. An unresolvable line becomes an item with
no variant link rather than a dropped line — dropping it would change the order total and
make the migrated order disagree with the invoice the customer already has.

**Totals are copied, never recomputed.** `subtotal`, `discount_total`, `shipping_total`,
`tax_total` and `grand_total` come from `wc_orders` + `wc_order_operational_data` as
recorded. Recomputing from line items would produce a different number for any order whose
prices, tax rate or shipping have changed since — i.e. most of them.

### 7. Coupons attach by code only if the code still exists

176 coupon line items. `Order.coupon` is an FK to `checkout.Coupon` with `SET_NULL`. A
legacy coupon whose code no longer exists leaves the FK null; the discount is already in
`discount_total` as money, so nothing is lost but the attribution.

### 8. Stock is not touched

Migrated orders are history. They must not reserve, commit or adjust stock — every one of
them was already fulfilled or abandoned in WooCommerce, and `commit_sale` on 4,096 orders
would drive live inventory to nonsense. The importer writes `Order`/`OrderItem` rows
directly and never calls `apps.inventory.services`.

---

## Tasks

1. **`extract_wp_orders --store --out`** — reader functions + artifact, mirroring
   Plan-22. Includes the intl `posts`/`postmeta` fallback for the 13 un-backfilled orders.
2. **The status/gateway/number transforms**, pure functions, tested against the real
   distribution above.
3. **`importers/orders.py`** — idempotent on `(source, legacy_number)`, linking through
   `LegacyIdentity`.
4. **`import_orders [--dry-run] [--since]`** + fixtures for all three stores.
5. **A reconciliation report** — per store: counts by mapped status, money totals against
   the WooCommerce totals, and every skipped row with its reason. Counts only in the repo.
6. **Guard the revenue seam**: a test asserting no migrated order lands in a
   `REVENUE_STATUSES` state without `date_paid_gmt`, so ruling 1 cannot silently regress.

---

## Decision needed — the 2,277 unpaid bank-transfer orders

Nobody paid for these. ₦34.2M on NG-current alone, the oldest from 2023, the newest from
**17:23 today**. WooCommerce never expired them, so they have simply accumulated.

They must not be `on_hold` (ruling 1). The remaining question is a business one:

- **`expired`** — treat them as abandoned. Honest, keeps them out of revenue, and matches
  what they are: 48% of NG orders picked bank transfer and never sent the money.
- **`pending_payment`** — treat them as live debts. They then appear in the admin's
  "Awaiting payment" queue, which is 2,277 rows of mostly-dead leads.
- **Split by age** — `pending_payment` if created within N days of cutover, `expired`
  otherwise. More faithful, and the only option that needs a number from you.

My recommendation is **`expired`, with a one-off CSV of the last 30 days' worth** so
anything genuinely still live can be chased by hand without putting 2,277 rows into a
working queue. Either way it is not revenue.

Worth knowing separately: **48% of NG orders choose bank transfer and never pay.** That is
a conversion problem this migration merely surfaces, not one it creates.
