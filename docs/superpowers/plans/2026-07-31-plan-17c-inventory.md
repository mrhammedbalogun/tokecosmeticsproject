# Plan-17c — warehouses, the inventory grid, the CSV wizard, unpriced markets

Scope defined by `docs/superpowers/specs/2026-07-30-plan-17a-admin-catalog-design.md`, which
sliced Plan-17 into a/b/c and deferred these four to 17c. Branch `plan-17c-inventory` off
`main` (`3614067`).

---

## Grounding (measured in production 2026-07-31 — do not re-derive)

| | |
|---|---|
| warehouses | 2, both active, **both `priority = 1`** |
| Lagos HQ | `location NG`, serves **NG, ZZ** |
| UK Warehouse | `location GB`, serves **GB, US, CA, ZZ** |
| stock rows | 122 — **all 122 in Lagos HQ** |
| stock rows in UK Warehouse | **0** |
| variants with no stock row anywhere | 0 |
| quantities in use | `[0, 99, 100]` — the Plan-21 placeholder, minus one test order |
| rows at or below the low-stock threshold (5) | 5 |
| stock movements | 246 — 244 `migration`, 1 `sale`, 1 `reservation` |
| prices | 121, all NGN · **0 country overrides** |

**Backend that already exists:** `StockItemAdminViewSet` (list, create, `adjust`),
`StockMovementListView`, stock CSV export and import. `import_stock_csv` already
**creates** rows as well as updating them, and collects per-row errors rather than aborting.

**Backend that does not exist:** any `Warehouse` endpoint at all, a dry-run for the CSV
import, and an unpriced-per-market query.

---

## THE FINDING THAT OUTRANKS THE REST OF THIS PLAN

**Every stock row is in Lagos HQ. The UK Warehouse holds nothing.**

`inventory/services.reserve()` filters candidate rows by
`warehouse__is_active=True, warehouse__serves_countries=country`. Lagos HQ serves **NG and
ZZ**; the UK Warehouse serves **GB, US and CA** — and has no stock rows at all. So:

| market | reserves from | outcome |
|---|---|---|
| NG | Lagos HQ | works |
| ZZ (Rest of World) | both serve it; Lagos HQ wins on pk | works |
| **GB, US, CA** | **only the UK Warehouse** | **no stock rows → reservation fails → checkout fails** |

So those three markets are blocked **twice**: no price in their currency (already known), and
now no stock in any warehouse that serves them. The pricing half was visible on the products
list; this half was not visible anywhere.

It is not urgent — only Paystack is certified, so NG is the sole sellable market by design —
but it means "add GBP prices" would **not** have been enough to open the UK, and somebody
would have found that out at the first failed checkout. 17c is where it gets fixed, because
the fix is exactly what this plan builds: a way to create stock rows in a second warehouse.

**Related, and now quantified:** 17a Task 7 recorded that there is no admin path to start
stocking a variant in a second warehouse. There *is* one — the stock CSV import creates
rows — but it is a file upload with no dry-run, which is a poor first experience of a
capability three markets depend on.

---

## Design rulings

### 1. Warehouse CRUD is a new admin surface, so it costs four declarations

`ADMIN_SURFACE`, the role matrix, the audit guard, and `test_audit.py`'s behavioural
`WRITE_CASES`. All four, as Plan-17a Task 1 learned the hard way. Scope
`products.manage`, consistent with every other catalogue and inventory endpoint.

**Deleting a warehouse is not offered.** `StockItem.warehouse` is `on_delete=CASCADE`, so
deleting one silently destroys every stock row it holds and every movement's context.
Deactivating (`is_active=False`) removes it from reservation without touching history, which
is what "remove this warehouse" actually means.

### 2. The CSV wizard needs a dry-run, and that is a backend change

The master spec asks for **upload → column map → dry-run report → apply**. `import_stock_csv`
applies immediately, so a dry-run mode is added that runs the same row logic and reports what
*would* happen without writing. One code path with a flag, never a parallel implementation —
a dry-run that can disagree with the real thing is worse than none.

### 3. The inventory grid is variant × warehouse, and shows what is missing

A cell with no `StockItem` is the thing this screen exists to surface — 122 of the 244
possible cells are empty today, and all 122 empty ones are the UK Warehouse. So an empty cell
is rendered as an actionable absence, not a blank.

### 4. Country-level price overrides: DECISION NEEDED

17a made the Prices grid **lock** any cell where a country override exists, with a pointer to
17c. Production has zero overrides, so nothing is locked today — but if 17c does not add
write support, that lock is permanent and points at nothing.

**Recommendation: do not build override editing.** All four markets are NGN-only and two are
blocked on stock as well; a per-country price is a refinement for a business selling in
several currencies, which this one is not yet. Instead, **change the lock's message** from
"arrives in 17c" to a plain statement that country prices are managed in the database. Cheap,
honest, and reversible when a second currency actually earns money.

---

## Tasks

1. **Backend: `WarehouseAdminViewSet`** — CRUD minus delete, `serves_countries` writable,
   plus the four guard declarations. TDD.
2. **Backend: CSV dry-run + unpriced-per-market endpoint.** `?dry_run=1` on the stock import;
   a read endpoint listing variants with no price in a given currency.
3. **Admin: `/inventory`** — the variant × warehouse grid, low-stock filter, movement drawer,
   and the Adjust modal reused from 17a Task 7.
4. **Admin: create a stock row where none exists** — the gap above, from the grid's empty
   cells. This is the task that unblocks GB/US/CA.
5. **Admin: warehouse manager** — list, edit, `serves_countries`, priority, activate/deactivate.
6. **Admin: CSV import wizard** — upload, map columns, dry-run report, apply.
7. **Admin: unpriced-per-market checklist.**
8. **Walkthrough, then CHECKPOINT.**

Tasks 3 and 4 come before 5–7 deliberately: they are what makes the UK Warehouse usable, and
everything after them is convenience.

## Risks

- **Both warehouses are `priority = 1`.** Allocation sorts by `(priority, pk)`, so Lagos HQ
  wins every tie today and the behaviour is deterministic. It is still an unset dial: the
  moment the UK Warehouse holds stock, ZZ orders will keep going to Lagos on pk order alone.
  The warehouse editor should make priority visible, and Task 5 should say what it does.
- **Three checkpoints are now outstanding** — Plan-17a's, 17b's, and this one. Nothing in any
  of the three has been walked in a browser.
