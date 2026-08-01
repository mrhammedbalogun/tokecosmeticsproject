# Plan-20 — dashboard and reports

Master spec: `master-tokerebuild.md` §Plan-20-admin-dashboard-reports. Branch off `main`
(`75c9ca1`).

> **REVISED after a Fable review**, which corrected more of this than it confirmed: my
> sequencing argument attacked a strawman, my objection to the XLSX pipeline named the
> wrong reason, and my charting instinct broke Hammed's own "boring over clever" rule.
> What changed is recorded at the bottom rather than folded in silently.

---

## Grounding (measured in production 2026-08-01 — do not re-derive)

| | |
|---|---|
| Orders | **1** (`processing`) · 1 order item · 1 payment · **0 refunds** |
| Customers | **1** · Coupons / redemptions: 0 / 0 |
| Currencies in use | NGN only |
| `reports.view` scope | declared in `rbac.py:95` (Owner + Manager) · **no endpoint uses it** |
| `/reports` nav item | exists in `nav.ts:43` · **404s** |
| Dashboard nav item | `scopes: []` (`nav.ts:30`) — **every staff member lands there** |
| Charting library | none in `admin/package.json` |
| Celery | configured; `low_stock_digest` hourly, `abandon_stale_carts` every 30 min |

**Five facts shape this plan:**

1. **There is one order.** Plan-23 imports **879 legacy orders** from both WooCommerce
   stores — that is the data this stage exists to summarise.

2. **`reports.view` is the third orphaned scope.** `cms.manage` was orphaned before
   Plan-19 and `settings.manage` before 19b. Each was found by grounding, never by a test.
   The pattern is now named: this project declares scopes a plan or two before anything
   uses them, and the guards do not catch it because a scope with no endpoint breaks
   nothing.

3. **`payment.amount` IS NOT CASH RECEIVED.** On an accepted discrepancy,
   `confirm_manual_receipt` leaves `payment.amount` at the order total and records what
   actually arrived in `raw_response["manual_receipt"][ref]["amount_received"]`
   (`payments/services.py:420-428`). Any revenue figure built on `SUM(payment.amount)`
   would silently report the invoiced amount as though it were money in the bank.

4. **`OrderItem` cannot be attributed to a category or a brand on its own.** It snapshots
   `product_name`, `sku` and prices only; category and brand live behind
   `variant → product`, and `variant` is `null=True, on_delete=SET_NULL`
   (`orders/models.py:133-135`). Plan-23 deliberately imports international items with no
   variant, so a sales-by-category report **will not** reconcile to a revenue report
   unless the gap is modelled explicitly.

5. **The dashboard's own tiles are stale copy.** `(shell)/page.tsx:41` prints "Coming in a
   later plan." under **every** tile, including the eight sections that now exist.

---

## Design rulings

### 1. No `DailySalesRollup` — and the reason is Plan-23, not performance

The performance case is real (880 orders behind `Index(["status", "-placed_at"])` is a
`GROUP BY`, and Plan-16 Task 6 measured this table's indexes at 200k rows), but it is not
the decisive one. **A nightly incremental rollup materialises "yesterday". Plan-23 then
bulk-inserts 879 orders whose `placed_at` spans years**, so every historical row the
rollup had written is wrong the moment the import runs — and the spec never scoped the
full-rebuild command that would be needed to repair it.

Deferral is only honest if the seam exists, so it does:

- **Every aggregate goes through one module**, `apps/analytics/queries.py`. Views call
  functions there and never write their own ORM aggregation, so a rollup can later slot in
  behind the same signatures.
- **The trigger is written down**: revisit at ~100k orders, or when a report's p95 exceeds
  ~500ms on the VPS. Both are measurable; "it feels slow" is not.
- **Whoever builds it owns a full rebuild path**, because any bulk import invalidates
  history. That sentence is the deliverable of this ruling.

### 2. No XLSX-to-S3 — because it breaks this codebase's egress discipline

Over-building was my objection and it was the weaker one. The real problem is that a
signed S3 link is **an export with no scope check and no read-audit**: anyone holding the
URL gets the file, and a top-customers report contains customer emails.

This repo already decided how bulk egress works, and wrote the reasoning down:
`AdminOrderCSVExportView` sits behind `orders.manage` — a scope ABOVE the list's
`orders.view` — and sets `audit_reads = True` (`orders/views.py:186`), because "a file with
every customer's email is bulk egress, which is a different act from working the order
desk". An S3 artifact quietly opts out of both halves.

So: **CSV streaming only**, and the same rules apply to it —

- Report exports are **read-audited**, like the order export.
- **`reports.view` alone does not authorise a bulk export.** Viewing an aggregate is not
  the same act as taking a file of customer emails; exports that name customers require
  `orders.manage`, matching the existing precedent exactly.

The PDF summary is dropped too: WeasyPrint is here for invoices, and a PDF of a dashboard
is a screenshot with extra steps.

### 3. Cut the donut, then the charting dependency mostly evaporates

My instinct was to avoid a dependency by hand-rolling charts. That is backwards for a
codebase maintained by one person — hand-rolled axis scaling, ticks and tooltips is exactly
the bespoke cleverness Hammed's standing preference rules out.

Attack the scope first: **an orders-by-status donut is decoration** for a store doing a
handful of orders a day, a status count strip says more in less space, and a donut actively
invites the modelling mistake `orders/models.py` warns about — needs-review is a *flag*,
not a status, so it can never be a slice.

That leaves **one revenue-over-time chart**. If it stays single-series, dependency-free SVG
bars are defensible. The moment it needs per-currency series (Plan-23 guarantees it will),
take `recharts` without apologising.

### 4. Name the metrics, in the plan, before writing a query

Plan-28 (accounting) inherits whatever this stage decides, and UAT will churn on any
number nobody can explain. So:

- **Revenue = `SUM(Order.grand_total)`** over an explicit status set, never
  `SUM(payment.amount)` (ruling ground 3). The status set and whether refunds net out via
  `Refund` rows is stated on the report itself, not just in code.
- **Cash actually received is out of scope for this stage.** It lives in
  `raw_response["manual_receipt"]` and reconciling invoiced-vs-received is Plan-28's job.
- **Category/brand reports carry an explicit "unattributed" row** for items whose variant
  is NULL. A silent omission would make the category total disagree with the revenue total
  and somebody would find it during UAT.
- **Coupon performance:** the redemption ledger has **no amount column**
  (`checkout/models.py:44-56`), so discount value needs the soft join
  `CouponRedemption.order_number → Order.number → discount_total`. And Plan-23 creates no
  redemption rows for migrated coupon lines, so historical coupon performance legitimately
  starts at zero — say so on the report rather than letting it read as "no coupons ever
  worked".
- **"Abandoned" is ambiguous here and must be disambiguated on screen.**
  `abandon_stale_carts` flags carts idle >3h, but the abandonment that costs this store
  money is an **expired bank-transfer order** (the 24-hour hold). The KPI says which one it
  counts.

### 5. The dashboard counts and links; it never re-derives

17c owns low stock and 18a owns needs-attention. The widgets call those endpoints —
`/admin/stock/grid/?low_stock=1` and the orders queue — rather than reimplementing the
predicates. Low stock in particular is already defined twice and identically (the digest
and the grid both filter `quantity <= threshold` while displaying `available`); a third
definition inside `apps/analytics/` is precisely the drift that rider warned about.

**And the dashboard must degrade, not 403.** `nav.ts:30` gives it `scopes: []`, so Support
lands there holding neither `reports.view` nor `products.manage`. KPI cards they cannot see
are omitted; the page still works. Deltas against a zero previous period render "—", never
`NaN` or `∞`.

---

## Sequencing

**Ship Plan-20 now, before the migration** — Plan-26's UAT names "report export" as a
scenario, so it cannot slide past 25/26, and Plan-27's cutover watch ("order volume vs the
same weekday last week") IS the delta card this stage builds.

**20a — Reports.** `apps/analytics/queries.py`, the endpoints, `reports.view` finally used,
read-audited CSV export, and `/reports`. Works at any data volume and closes the orphan.

**20b — Dashboard.** KPI cards with deltas, one revenue chart, a status strip, and widgets
that count what 17c/18a already own. Also retires the "Coming in a later plan" copy.

**Verification is where the migration risk gets handled, not by delaying.** Seeded factory
data with known expected values is a *better* correctness check than one real order — but
the seed must produce **migration-shaped** rows, or the first render over Plan-23's output
has no owner:

- at least two currencies (the no-FX-mixing rule is unexercisable on NGN-only data),
- items with `variant=NULL` (ruling 4's unattributed bucket),
- `legacy_number` set, and historical `completed`/`refunded` statuses spanning months.

The seed command must be impossible to run against production; this database is live.

---

## Risks and riders

- **18b's deferral expires at Plan-22, and it collides with this stage.** 18a deferred
  customers because "production holds 1 customer"; Plan-22 imports hundreds, with WP
  password compatibility and **no admin surface to spot-check them on** — Customers and
  Reviews 404 exactly as Reports does today. 18b's spec also wants per-customer "orders
  count, lifetime value", which is the same aggregate family as this stage's top-customers
  report. **Ruling needed from Hammed:** either 18b lands with Plan-22, or Plan-20's
  customer aggregates are explicitly the shared layer 18b consumes. Two independent LTV
  implementations will disagree.
- **A tripwire test guards the customers scope.**
  `test_admin_search.py::test_the_customers_section_is_the_only_underived_one_and_it_is_pinned`
  is designed to fail the day a customers endpoint is routed. If a top-customers report
  routes one, that test must be rewired to derive from it — it is a tripwire, not a
  regression.
- **`low_stock_digest` becomes hourly spam after Plan-21.** It runs every 3600s with no
  change detection (`base.py:456-458`). Today it finds nothing; with real stock and 30
  chronically low SKUs it emails the identical list 24 times a day and trains staff to
  ignore it. Demote to daily or send only on change — cheap, and this stage's low-stock
  widget is the natural moment.
- **Plan-23's `verify_orders` must stay independent of these endpoints.** Reconciling the
  import against the analytics layer would be marking its own homework.

---

## What the Fable review changed

- **My sequencing argument was a strawman and is withdrawn.** I argued the dashboard should
  perhaps wait for Plan-23 because hand-checking against one order proves nothing — but the
  spec never proposed that; it proposes seeded factory data, which is a *better* check
  because the expected values are known. The real risk is narrower and now handled as a
  verification requirement: seed migration-SHAPED rows so Plan-23's output is not the first
  thing this code ever meets.
- **My XLSX objection named the wrong reason.** I called it over-built. It is primarily an
  egress-discipline break — no scope check, no read-audit, customer emails in a bucket —
  measured against a rule this repo already wrote down for the order export. That also
  produced a ruling I did not have: report exports must themselves be read-audited and
  gated above `reports.view`.
- **My charting instinct broke the standing preference.** Hand-rolling a chart library to
  dodge a dependency is bespoke cleverness in a codebase one person maintains. Cutting the
  donut is the better move, and it makes the dependency question small.
- **The rollup deferral was right but incomplete.** Without the query-module seam, the
  written trigger, and the rebuild-after-import note, "defer" is just unbuilt work.
- **Five things I would have quietly dropped** are now rulings: the `payment.amount` caveat,
  category attribution through a nullable variant, the coupon ledger's missing amount
  column, which "abandoned" is meant, and the dashboard's scope-less landing page.
- **It found the adjacent gap I had not looked for**: 18b's justification expiring at
  Plan-22, and its LTV aggregates colliding with this stage's.
