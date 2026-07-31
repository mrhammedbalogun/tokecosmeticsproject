# Plan-17b — the variant option-matrix builder

**Status:** design spec, **awaiting Hammed's decision on §4**. Grounded against production
2026-07-30.

Master spec: `master-tokerebuild.md` § Plan-17. Slice defined by
`docs/superpowers/specs/2026-07-30-plan-17a-admin-catalog-design.md`, which deferred the
option-matrix builder to 17b so 17a could ship a usable editor first.

---

## 1. What the catalogue actually looks like

Measured, not assumed. Every number below changed something in this spec.

| | |
|---|---|
| variants | 122 |
| variants with **no** option data | 52 — every single-variant product, exactly |
| multi-variant products | 18 |
| products with **two** option axes | **8** |
| variants carrying two axes at once | 43 |
| distinct option KEY names in use | **4** |

The four key names are `Product Size` (55 variants), `Price Options` (43), `Size` (12) and
`Shea Variant` (3). **`Product Size` and `Size` are the same axis under two names** — WooCommerce
attribute labels carried through the Plan-21 import.

The 8 two-axis products are genuine Cartesian products, e.g. `toke-coco-shea-butter`:

```
Product Size : 35g (sample) · 80g · 175g · 275g
Price Options: Pieces · Pack Price
```

So a matrix builder has real work to do — this is not a feature built for a hypothetical.

---

## 2. A live bug found while grounding this

**The storefront variant picker labels every option with the product's name.**

`storefront/src/components/product/VariantPicker.tsx:22` renders `{v.name}`, and
`ProductVariant.name` on these products is the product name repeated. Confirmed against the
live API just now:

```
GET /api/v1/products/toke-coco-shea-butter/   (X-Country: NG)

button label: 'Toke coco shea butter'  ₦500      {Product Size: 35g (sample), Price Options: Pieces}
button label: 'Toke coco shea butter'  ₦4,800    {Product Size: 80g,          Price Options: Pack Price}
button label: 'Toke coco shea butter'  ₦900      {Product Size: 80g,          Price Options: Pieces}
button label: 'Toke coco shea butter'  ₦1,800    {Product Size: 175g,         Price Options: Pieces}
button label: 'Toke coco shea butter'  ₦14,800   {Product Size: 175g,         Price Options: Pack Price}
button label: 'Toke coco shea butter'  ₦16,800   {Product Size: 275g,         Price Options: Pieces}
button label: 'Toke coco shea butter'  ₦15,500   {Product Size: 275g,         Price Options: Pack Price}
```

**Seven identical buttons priced ₦500 to ₦16,800, on a live product.** A shopper cannot tell
them apart, and `option_values` — which would distinguish them perfectly — is already in the
API response and simply unused.

**8 products are affected** (every two-axis product). This is not 17b work and should not
wait for 17b: it is a few lines in `VariantPicker` to label from `option_values`, falling
back to `name`. **Recommend fixing it first, separately.**

Two smaller things noticed in the same data, for Hammed rather than for code:

- **The 275g prices look wrong.** At 175g, Pieces ₦1,800 / Pack ₦14,800. At 275g, Pieces
  ₦16,800 / Pack ₦15,500 — Pieces dearer than the pack, and the pattern inverts. Worth a
  human look; migrated pricing, not something this plan should "fix" by guessing.
- **All stock is 100**, the Plan-21 placeholder (`docs/migration/stock-todo.csv`). Harmless
  now, but see §5.

---

## 3. What 17b builds

Per the master spec: define option names and values, click **Generate variants**, get the
grid of all combinations with per-variant SKU (auto-suggested), and adding or removing a
value regenerates **without losing filled rows**. Single-variant products skip the builder.

Concretely, on the editor's Variants tab:

1. **Option editor** — ordered list of axes, each with an ordered list of values. Seeded from
   the product's existing variants when it has any.
2. **Generate** — computes the Cartesian product, shows which combinations are new, which
   already exist, and which existing variants no longer match any combination.
3. **The grid** — one row per combination: SKU (suggested, editable), the option values,
   and whether it exists yet. Prices and stock stay where 17a put them; this screen creates
   variants, it does not re-implement the Prices tab.
4. **Nothing is written until Apply**, and Apply never deletes. Variants that fall outside
   the new matrix are listed and left alone — deleting a variant destroys its price rows,
   its stock, and its order history links.

**Naming.** `ProductVariant.name` is what the storefront shows (§2), so generated variants
must be named from their option values — `"175g · Pack Price"`, not the product name. This
is the builder's most valuable single behaviour.

---

## 4. THE DECISION: where option definitions live

This is the one thing I need from you before writing the implementation plan.

Today there is **no schema for options at all**. `ProductVariant.option_values` is a bare
`JSONField`, and a product's axes exist only as an emergent property of its variants.

**Option A — derive from variants. No migration.**
Read the axes back out of `option_values` when the tab loads; hold the editor's state in the
browser; write plain `option_values` dicts on Apply.

- Nothing to migrate, nothing to backfill, no new tables.
- **Axis order is not stable.** Django stores this as Postgres `jsonb`, which does *not*
  preserve key insertion order — it orders keys by length then bytewise. So "Product Size"
  then "Price Options" is not something the database can be asked to remember.
- No way to define an axis before any variant uses it, and nowhere to record that an axis is
  a colour swatch rather than a dropdown.

**Option B — add `ProductOption` and `ProductOptionValue`. One migration.**
The Shopify model, and what the master spec implicitly assumes.

- Stable axis and value ordering; a real home for future swatch/colour UI.
- Makes the inconsistent key names (§1) fixable as data rather than as string surgery across
  122 JSON blobs.
- Costs a migration and a backfill of 70 variants on a live database, plus keeping
  `option_values` in step for the storefront, which reads it today.

**My recommendation: A, and revisit at 17c.** The order instability is real but cosmetic, and
it only bites the 8 two-axis products. Adding two tables to a live catalogue to fix display
order — while the actual customer-visible defect is §2's picker, which needs neither — is the
wrong trade this month. If swatches are ever wanted, B becomes worth it and the backfill is
no harder then than now.

**But this is your call, and it is the expensive one to reverse.**

---

## 5. Things this spec deliberately does not do

- **`Price Options: Pieces / Pack Price` is not a product option**, it is a wholesale price
  tier wearing a variant's clothes. It doubles the variant count on 8 products, and once real
  stock replaces the placeholder 100s, the same physical jars will be counted twice — once
  under Pieces and once under Pack Price. 17b will faithfully reproduce whatever modelling it
  is given, and a matrix builder makes creating more of it easier. **Remodelling it is a
  business decision, not a refactor**, so it is named here and left alone.
- **No variant deletion.** See §3.4.
- **No bulk price entry in the matrix.** 17a's Prices tab owns that; two editors for one
  value is how they disagree.

---

## 6. Open question for Hammed

Beyond §4: **should `Price Options` remain an axis at all?** If those 8 products should
instead be 2 variants each with a wholesale price on the same variant, that is a data
change worth doing *before* a builder makes the current shape easier to extend — and it
interacts with how you eventually price bulk orders.
