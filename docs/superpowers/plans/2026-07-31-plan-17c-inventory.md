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

> **CORRECTED 2026-07-31 after a Fable review.** The section below was originally headed
> "THE FINDING THAT OUTRANKS THE REST OF THIS PLAN" and used to justify doing 17c next. That
> was overclaimed, and the section contradicted itself: it says "not urgent — only Paystack
> is certified" and then orders the tasks as though the finding were urgent.
>
> **GB, US and CA are blocked three ways: no certified payment method, no non-NGN prices,
> and no stock. This plan fixes the third only** — and stock rows are worth nothing until
> somebody physically counts what is in the UK warehouse. A dramatic finding about markets
> that cannot be sold to was used to justify inventory tooling ahead of the work that makes
> the market we CAN sell to function. See "Sequencing" below.
>
> The finding itself is real and worth recording. Its rank was not.

## The UK Warehouse holds no stock

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

It is not urgent — only Paystack is certified, so NG is the sole sellable market by design.
What it is worth is that **"add GBP prices" would not have been enough to open the UK**, and
the way that would otherwise have surfaced is a customer's failed checkout. Recording it now
means the day someone decides to open the UK, the list of what is missing is already written
down: a payment method, prices in GBP, and stock that physically exists.

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

### 1b. `serves_countries` is the most dangerous field on this surface

Added after the Fable review, which pointed out that Task 1 quietly makes it writable with no
note about blast radius — while warehouse DELETION, which is less dangerous, got a whole
ruling.

`inventory/services.reserve()` filters candidates on
`warehouse__is_active=True, warehouse__serves_countries=country`
(`backend/apps/inventory/services.py:20,52`). **Unticking `NG` on Lagos HQ removes the only
warehouse serving Nigeria, and every checkout in the only sellable market fails** — with no
error anywhere until a customer tries to buy something. It looks like an ordinary checkbox
edit and it is closer to a kill switch.

So: `serves_countries` and `is_active` both get a confirmation naming the consequence in
plain words ("Nigeria will have no warehouse. Checkout will fail there."), computed from the
other warehouses rather than asserted. Editing a warehouse's name or priority does not.

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
several currencies, which this one is not yet.

**CORRECTED after the Fable review, twice over.**

**There are THREE promises to retract, not one.** Verified:

```
admin/src/lib/product-prices.ts:86    "Country prices arrive in 17c."
admin/src/lib/product-prices.ts:89    "Scheduled prices arrive in 17c."
admin/src/components/product/PricesPanel.tsx:133
                                     "Country-specific and scheduled prices arrive in a
                                      later slice (17c)."
```

17a locks cells for **scheduled** prices too, not only country overrides, and both messages
promise 17c. Rewording one of the three would have left the grid still promising something
nobody intends to build.

**And the replacement wording was wrong.** "Managed in the database" is an invitation to
hand-edit production SQL. The message should say what is true and point nowhere:
*"Country-specific prices cannot be edited here."* Same for the scheduled case.

---

## Sequencing — THIS PLAN IS NOT NEXT

Added after the Fable review, which argued the point better than the original ordering did.

Three checkpoints are outstanding (17a, 17b, and this one) and **nothing built in any of them
has been walked in a browser** — roughly 536 admin tests, every one against mocks. Mocked
response shapes drift from real DRF output silently, and 17b was built on 17a screens nobody
has seen render. Each further plan compounds the rework if a checkpoint fails.

Meanwhile **Plan-18 is unbuilt, and bank transfer is the only live payment method.** This
repository's own GIG research says it plainly (`docs/gigimplementationresearch.md`): an NG
customer can pay and never be shipped, because there is no admin path to confirm receipt. A
store that can take money it cannot fulfil is not half-launched.

**The order:**

1. **Walk the 17a and 17b checkpoints.** Hours, not days.
2. **Plan-18** — makes the one sellable market actually work end to end.
3. **17c**, as below, trimmed to what serves NG.
4. **GIG**, once they answer `docs/gig-reply-capture-preshipment.md`.

## Tasks

Reordered: the NG operations tooling first, the GB/US/CA framing dropped.

0. **Fix the 8 weightless variants** (`docs/migration/pricing-todo.csv` names them). Half an
   hour of data entry that has been flagged in three documents and scheduled in none. Every
   GIG quote is computed from weight, so this blocks that work and nothing else depends on it.
1. **Backend: `WarehouseAdminViewSet`** — CRUD minus delete, `serves_countries` writable
   behind ruling 1b's confirmation, plus the four guard declarations. TDD.
2. **Backend: CSV dry-run + unpriced-per-market endpoint.** `?dry_run=1` on the stock import;
   a read endpoint listing variants with no price in a given currency.
3. **Admin: `/inventory`** — the variant × warehouse grid, low-stock filter, movement drawer,
   and the Adjust modal reused from 17a Task 7. **This is the daily-use screen for NG**, and
   the reason 17c is worth doing at all.
4. **Admin: create a stock row where none exists.** Closes 17a Task 7's recorded gap. Useful
   for NG the moment a second Nigerian warehouse exists; it also happens to be what the UK
   would need one day.
5. **Admin: warehouse manager** — list, edit, `serves_countries`, priority,
   activate/deactivate.
6. **Admin: CSV import wizard** — upload, map columns, dry-run report, apply.
7. **Admin: unpriced-per-market checklist**, plus retracting the three 17c promises in
   ruling 4.
8. **Walkthrough, then CHECKPOINT.**

## Risks

- **Both warehouses are `priority = 1`.** Allocation sorts by `(priority, pk)`, so Lagos HQ
  wins every tie today and the behaviour is deterministic. It is still an unset dial: the
  moment the UK Warehouse holds stock, ZZ orders keep going to Lagos on pk order alone.
  **Task 5 must WARN on a duplicate priority, not merely display it** — "make it visible" was
  the original wording and it is not a fix for a dial nobody set, as the Fable review pointed
  out. Showing a number nobody chose next to another identical number nobody chose does not
  tell anybody a decision is owed.
- **Three checkpoints are now outstanding** — Plan-17a's, 17b's, and this one. Nothing in any
  of the three has been walked in a browser.
