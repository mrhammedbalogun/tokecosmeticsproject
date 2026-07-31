# Plan-17b — the variant option-matrix builder

Design spec: `docs/superpowers/specs/2026-07-30-plan-17b-variant-matrix-design.md`.
**§4 decided by Hammed 2026-07-30: Option A — option definitions are derived from the
variants themselves. No new tables, no migration.**

Branch `plan-17b-variant-matrix` off `main` (`e5410db`).

---

## Grounding facts (measured 2026-07-30, do not re-derive)

| | |
|---|---|
| variants | 122 · **52 with no option data** (every single-variant product) |
| multi-variant products | 18 · **8 of them two-axis** |
| variants carrying two axes at once | 43 |
| distinct option key names | 4 — `Product Size` (55), `Price Options` (43), `Size` (12), `Shea Variant` (3) |
| largest matrix in production | `toke-coco-shea-butter`, 7 variants over 4 sizes × 2 price options |

`Product Size` and `Size` are the same axis under two WooCommerce labels. So is a chunk of
what 17b is for: **renaming an axis is a first-class operation here, not a nicety.**

**Backend needs nothing new.** `POST /admin/variants/` creates, `PATCH /admin/variants/{id}/`
updates, and 17a's `?product=` filter reads them back. No new endpoint, no guard
declarations, no migration.

**Already fixed, and why it matters here:** `storefront/src/lib/variant-label.ts` now labels
the picker from `option_values` rather than `name` (commit `e5410db`). That was a live bug —
seven identical buttons at seven prices. It also removes the pressure to treat `name` as
load-bearing, which shapes Task 4 below.

---

## Design rulings

### 1. Axis ORDER is arbitrary, stable, and said out loud

Option A's accepted cost. Django stores `option_values` as Postgres `jsonb`, which orders
keys by length then bytewise rather than by insertion — so no axis order anybody chooses can
be persisted. It IS stable between renders, so the builder will not reshuffle under a user;
it is simply not their choice.

The UI states this once, near the axis list, rather than pretending otherwise. Within an
editing session the user's own ordering is honoured; it just does not survive a reload.

### 2. Apply CREATES; it never deletes

A variant carries price rows, stock rows, and links from historical order lines. Deleting one
to "clean up the matrix" destroys all three. So combinations that exist but fall outside the
new matrix are **listed as orphans and left alone**, with a sentence saying why.

### 3. There is no transaction, so partial application must be legible

A 4×3 matrix is twelve `POST`s and there is no bulk endpoint. If the seventh collides on
SKU, six variants already exist. The UI reports exactly what was created and what failed, and
the failed rows stay on screen with their error and a Retry — the same shape as 17a's image
uploads. **Building a bulk endpoint to get atomicity is out of scope**: it is a new admin
route needing four guard declarations, for a screen used a few times a month.

### 4. Generated variants are NAMED from their options

`name` = the option values joined, `"175g · Pack Price"`. Never the product name — that is
precisely the defect `e5410db` fixed on the storefront, and a builder that recreated it would
undo that fix one product at a time.

### 5. A rename rewrites every variant of that product, and says so first

Renaming `Product Size` → `Size` means PATCHing `option_values` on each variant. That is the
whole point (it fixes the four-names mess), but it is a bulk write and must be confirmed with
the count in the sentence: "Rename on 7 variants?"

---

## Tasks

Sequential, two-stage review each, as 17a.

### Task 1 — `lib/variant-matrix.ts`: the pure logic

No React, no fetching. This is where the plan's whole risk lives, so it is TDD and first.

- `deriveAxes(variants)` → ordered axes with their distinct values, from `option_values`.
- `cartesian(axes)` → every combination, in a deterministic order.
- `diffMatrix(combinations, variants)` → `{ existing, missing, orphaned }`. A variant matches
  a combination when their option maps are equal — same keys, same values.
- `suggestSku(productSlug, combination, taken)` → a slug-shaped SKU, de-duplicated against
  SKUs already on screen.
- `variantName(combination)` → values joined, matching the storefront's `variantLabel`.
- Validation: no blank axis or value, no duplicate value within an axis, no duplicate axis
  name, and a **combination-count ceiling** (see Risks).

**Verify:** the production shapes as fixtures — a one-axis product, the 4×2 that is really 7
variants, and a single-variant product with no options at all.

### Task 2 — the option editor

In the Variants tab, above 17a's read-only table. Add/remove an axis, add/remove/reorder its
values, seeded from `deriveAxes`. Nothing is written here; it is all UI state until Task 3.

Single-variant products with no options show a "Add options to this product" affordance
rather than an empty grid — per the master spec, they skip the builder entirely.

**Verify:** open `toke-coco-shea-butter`, see `Product Size` with four values and
`Price Options` with two, in a stable order; add a value and see it appear.

### Task 3 — generate, diff and apply

Generate shows the diff from Task 1 as three groups: **will be created**, **already exists**,
and **no longer in the matrix** (orphans, untouched). Each new row carries an editable
suggested SKU and its generated name.

Apply POSTs the missing variants one at a time, reporting per row. Partial failure leaves the
successes in place and the failures on screen with their message.

**Verify:** add a value to a production-shaped fixture, apply, confirm only the new
combinations were created and every pre-existing variant kept its id, price and stock.

### Task 4 — rename an axis or a value

The migration-debris fix. Renaming rewrites `option_values` on every variant of the product,
confirmed with the count. Offer to rename `Product Size` → `Size` on the 55 variants that
need it, one product at a time.

Also here: **"Fix names from options"** for existing variants whose `name` is the product
name. Explicit and opt-in, never silent — it is a bulk write like any other.

**Verify:** rename an axis on a fixture, confirm every variant's `option_values` key changed
and nothing else did.

### Task 5 — live walkthrough, then CHECKPOINT

A real browser pass against real data, as 17a Task 9 (still outstanding — see Risks).

**CHECKPOINT: Hammed builds a two-axis product's variants from scratch.**

---

## Testing discipline

Unchanged. Backend needs no work, so this is vitest only: every function in Task 1, every
presentational component, Server Functions by mocking `global.fetch`. Server Component pages
are covered by the walkthrough, matching precedent.

## Non-goals

Carried from the spec: no variant deletion; no bulk price entry (17a's Prices tab owns it);
no `ProductOption` tables (that is §4's Option B, revisit at 17c); no swatch/colour UI, which
Option A has nowhere to record.

## Risks

- **A combination ceiling is required, not optional.** Three axes of five values is 125
  variants, each with price and stock rows, created by 125 sequential POSTs. The builder
  refuses above a threshold (propose **50**) and says why. Nothing in production approaches
  this; the ceiling exists because a builder makes it one careless click away.
- **`Price Options` is a wholesale price tier modelled as an option** (spec §5, still
  undecided). 17b will faithfully extend whatever shape it is given. If those 8 products are
  to be remodelled, doing it before this ships is much cheaper than after.
- **Plan-17a's checkpoint is still outstanding.** 17b builds on the editor that nobody has
  walked. If 17a's Variants tab has a defect, 17b sits on top of it.

---

## Task 5 — live walkthrough record (2026-07-31)

Same real stack as the 17a record (that file has the environment details). Walked on a
fresh draft product created through the 17a flow (`walkthrough-whip-butter`), i.e. the
zero-variant case the fixtures never covered.

**What passed:**

- Built Size (30ml, 50ml) × Shade (Light, Deep) from nothing: axis naming, value chips,
  add/remove, "4 combinations" counter live the whole time.
- Generate → the matrix diff listed 4 to create with editable SKUs → apply created
  exactly 4 variants. **DB verified**: option-derived names (`30ml · Light`), slugged
  SKUs, correct `option_values` — the Task 1 arithmetic holds against the real API.
- **The Task 4 rename, end to end.** Renaming the Shade axis to Tone surfaced the
  RenamePanel ("Rename on 4 variants" — the button that says its blast radius), and
  applying it rewrote **every** variant's `option_values` key from `Shade` to `Tone`
  and touched nothing else. DB verified, exactly the plan's own verify clause.
- The added-option guard: generating while the axes no longer match existing variants
  produced the explicit refusal-to-guess banner ("None of the existing variants fit
  this matrix… Nothing is deleted either way") instead of a silent create.

**One real bug:**

- **After "Create N variants" the variant list doubles client-side.** The created
  variants are appended to state that is then also refreshed from the server, so every
  row appears twice, React logs duplicate-key warnings (the keys are the new variant
  ids), and — worse — the *next* Generate counts the doubled list: it reported "8
  outside this matrix" and "would leave you with 12 variants where you probably want
  4" when the true numbers are 4 and 8. Reload fixes it (server state was always
  right: 4 rows). Harmless to data, actively misleading to the person deciding
  whether to apply — fix before the checkpoint if possible, otherwise tell the walker
  to reload after applying.

**Not exercised live:** the 50-combination ceiling (unit-tested only); the storefront
PDP rendering of the new labels.

**CHECKPOINT — still Hammed's to perform:** build a two-axis product's variants from
scratch, himself. The path is verified working end to end.

**CHECKPOINT SIGNED OFF — Hammed, 2026-07-31.** He built a two-axis product's variants
from scratch himself against the local stack, after the doubled-grid fix (`5c566cf`).
Plan-17b is closed.
