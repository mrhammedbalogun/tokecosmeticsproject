# Plan-20 — dashboard and reports

Master spec: `master-tokerebuild.md` §Plan-20-admin-dashboard-reports. Branch off `main`
(`75c9ca1`).

> **DRAFT — a Fable review is running.** Corrections will be recorded at the bottom rather
> than folded in silently, as in Plan-19.

---

## Grounding (measured in production 2026-08-01 — do not re-derive)

| | |
|---|---|
| Orders | **1** (`processing`) · 1 order item · 1 payment · **0 refunds** |
| Customers | **1** |
| Currencies in use | NGN only |
| Coupons / redemptions | 0 / 0 (the model shipped in 19b) |
| `reports.view` scope | declared in `rbac.py` (Owner + Manager) · **no endpoint uses it** |
| `/reports` nav item | exists in `admin/src/lib/nav.ts` · **404s** |
| Charting library | none in `admin/package.json` |
| Celery | configured and in use (inventory, notifications) |
| WeasyPrint | already a dependency (invoices) |

**Four facts shape this plan:**

1. **There is one order.** A dashboard is a lens over history, and there is no history. The
   spec's own verification says "seed 3 months of factory orders; dashboard numbers
   hand-checked against SQL" — an admission that this stage cannot be validated against
   production as it stands. **Plan-23 imports 879 legacy orders from both WooCommerce
   stores**, which is the data this stage exists to summarise.

2. **`reports.view` is the third orphaned scope.** `cms.manage` was orphaned before
   Plan-19 and `settings.manage` before 19b; both were found by grounding rather than by
   the tests. `reports.view` is granted to Owner and Manager and reaches nothing, and the
   nav shows a Reports link that 404s.

3. **The rollup table's premise is already contradicted in this repo.** The spec wants
   `DailySalesRollup` materialised nightly "so date-range queries stay instant". But
   `orders/models.py` carries `Index(fields=["status", "-placed_at"])`, and the Plan-16
   Task 6 comment beside its trigram indexes records a **measurement at 200,000 orders**.
   A store with 880 orders after Plan-23 does not need a materialised aggregate; it needs
   a `GROUP BY` over an indexed column.

4. **The dashboard's own tiles are stale copy.** `admin/src/app/(shell)/page.tsx:41`
   prints "Coming in a later plan." under **every** nav tile — including Orders, Products,
   Inventory, Content, Coupons and Settings, all of which now exist. This is the same
   class of stale promise Plan-17c retracted three of and 19c retracted a fourth.

---

## Design rulings (provisional, pending review)

### 1. No `DailySalesRollup`. Live aggregates, and a written trigger for revisiting

A materialised table is a second source of truth that can drift from the orders it
summarises, plus a nightly job to monitor and backfill. At 880 orders the query it
optimises is a `GROUP BY` over an indexed column.

**The trigger is written down rather than left to feel:** revisit when the orders table
passes ~100k rows, or when a report's p95 exceeds ~500ms on the VPS. Both are measurable;
"it feels slow" is not.

### 2. CSV, not XLSX-to-S3

Every export in this codebase already streams CSV (orders, stock, products), Excel opens
CSV natively, and the spec's XLSX path is an openpyxl Celery job writing to S3 behind a
signed link — three moving parts for a file a browser can download directly. The PDF
summary is likewise deferred: WeasyPrint is present for invoices, but a PDF of a dashboard
is a screenshot with extra steps.

### 3. Per-currency, never converted — and the UI must make that unmissable

The spec says report per currency with no FX mixing. That is right and it is also a trap:
a "Revenue" number that silently omits GBP orders is worse than one that shows both. So
totals are always labelled with their currency and a report spanning several shows them
side by side, never summed. Today this is academic (NGN only); after Plan-23 it will not be.

### 4. The dashboard shows what is ALREADY answerable, and links to the screens that answer it

18a shipped a needs-attention queue, 17c an inventory grid with a low-stock filter. The
dashboard must not reimplement either — it counts them and links. A second implementation
of "which orders need review" is a second thing to keep correct.

---

## Sequencing (provisional)

**20a — Reports backend + the reports screen.** The aggregate queries, `reports.view`
finally used, CSV export, and `/reports`. This is the half that works with any amount of
data and closes the orphan.

**20b — The dashboard.** KPI cards, the revenue chart, and the widgets that count what
17c/18a already own. Second because it is the half that needs history to mean anything.

**Open question this plan must answer, not dodge:** whether 20b should wait until after
**Plan-23** imports the 879 legacy orders. Building a dashboard against one order means
hand-checking every number against a dataset that proves nothing.
