/**
 * Per-axis view of a product's variants, for the multi-axis picker.
 *
 * A two-axis product (e.g. Size × Colour) used to render one pill per VARIANT, so 4 sizes
 * × 3 colours became 12 pills reading "1l · red", "1l · blue", … A shopper thinks in
 * axes — pick a size, pick a colour — so `VariantPicker` renders one selector per axis
 * and the PDP resolves the concrete variant from the answers.
 *
 * NOTE (2026-09-08): `pickVariant` used to live here — it landed a click on SOME variant
 * carrying the chosen value even when the rest of the selection could not be honoured,
 * which meant choosing a size silently chose a colour too. Nothing picks FOR the shopper
 * any more; see PdpContext.select, which keeps the answers that still fit and un-answers
 * the ones that don't.
 */
import type { Variant } from "@/lib/catalog";

export interface VariantAxis {
  name: string;
  values: string[];
}

function optionValue(variant: Variant, axis: string): string {
  return String(variant.option_values?.[axis] ?? "").trim();
}

/**
 * The distinct option axes across all variants, values in first-appearance order.
 * Variant order comes from the API (import order), which for sizes is ascending —
 * there is no reliable way to sort "1l"/"175g"/"Family pack" better than that.
 */
export function variantAxes(variants: Variant[]): VariantAxis[] {
  const axes: VariantAxis[] = [];
  for (const variant of variants) {
    for (const name of Object.keys(variant.option_values ?? {})) {
      const value = optionValue(variant, name);
      if (!value) continue;
      let axis = axes.find((a) => a.name === name);
      if (!axis) {
        axis = { name, values: [] };
        axes.push(axis);
      }
      if (!axis.values.includes(value)) axis.values.push(value);
    }
  }
  return axes;
}

/** Does this variant carry every one of these option values? A partial selection
 * matches every variant that agrees on the axes answered so far. */
export function variantMatches(variant: Variant, selections: Record<string, string>): boolean {
  return Object.entries(selections).every(
    ([axis, value]) => optionValue(variant, axis) === value,
  );
}

/** Every variant agreeing with the (possibly partial) selection. */
export function variantsMatching(
  variants: Variant[],
  selections: Record<string, string>,
): Variant[] {
  return variants.filter((v) => variantMatches(v, selections));
}

/** The variant matching every selection exactly, or null — combos can be missing
 * (a product need not offer every size in every colour). */
export function matchVariant(
  variants: Variant[],
  selections: Record<string, string>,
): Variant | null {
  return variants.find((v) => variantMatches(v, selections)) ?? null;
}
