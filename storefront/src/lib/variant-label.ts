/**
 * How a variant is named in the picker.
 *
 * ── THE BUG THIS FIXES ──────────────────────────────────────────────────────────────
 *
 * `VariantPicker` rendered `variant.name`, and on every product the Plan-21 import gave
 * two option axes, `ProductVariant.name` is the PRODUCT's name repeated. Measured on the
 * live API, `toke-coco-shea-butter` offered a shopper seven buttons all reading "Toke coco
 * shea butter", priced ₦500 to ₦16,800, with nothing to tell them apart — while
 * `option_values`, which distinguishes them exactly, was already in the same response and
 * unused. 8 products were affected.
 *
 * So the label is built from the option values, and `name` becomes the fallback for the
 * variants that have no option data — which is every single-variant product, and those
 * never render a picker at all (`variants.length <= 1` returns null).
 */
import type { Variant } from "@/lib/catalog";

/**
 * The button label: the option VALUES, joined.
 *
 * Values, not `key: value` pairs. On a size axis the values are already self-describing
 * ("175g", "500ml") and prefixing them with "Product Size:" makes a pill twice as wide and
 * no clearer. The axis NAMES go in the legend instead, where they are said once.
 *
 * Key order comes from the object as the API sent it. That is Postgres `jsonb`, which
 * orders keys by length then bytewise rather than by insertion — so the order is stable
 * between renders but is not something anybody chose. Fixing that needs a schema for
 * options, which is Plan-17b's open question; it does not block naming the buttons.
 */
export function variantLabel(variant: Variant): string {
  const values = Object.values(variant.option_values ?? {})
    .map((value) => String(value).trim())
    .filter(Boolean);

  return values.length ? values.join(" · ") : variant.name;
}

/**
 * The fieldset legend: the axis NAMES.
 *
 * Was hardcoded to "Size", which is wrong twice over — the axis is called `Product Size` on
 * 55 variants and `Price Options` on 43, and a two-axis product has two of them. Falls back
 * to "Options" when there is no option data to name.
 */
export function variantLegend(variants: Variant[]): string {
  const names: string[] = [];
  for (const variant of variants) {
    for (const key of Object.keys(variant.option_values ?? {})) {
      if (!names.includes(key)) names.push(key);
    }
  }
  return names.length ? names.join(" / ") : "Options";
}
