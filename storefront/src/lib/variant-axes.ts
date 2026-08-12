/**
 * Per-axis view of a product's variants, for the two-axis picker.
 *
 * A two-axis product (e.g. Size × Colour) used to render one pill per VARIANT, so 4 sizes
 * × 3 colours became 12 pills reading "1l · red", "1l · blue", … A shopper thinks in
 * axes — pick a size, pick a colour — so `VariantPicker` renders one selector per axis
 * and uses `pickVariant` to land on the concrete variant behind the combination.
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

/** The variant matching every selection exactly, or null — combos can be missing
 * (a product need not offer every size in every colour). */
export function matchVariant(
  variants: Variant[],
  selections: Record<string, string>,
): Variant | null {
  return (
    variants.find((v) =>
      Object.entries(selections).every(([axis, value]) => optionValue(v, axis) === value),
    ) ?? null
  );
}

/**
 * Where choosing `value` on `axis` lands, holding the other current selections when that
 * exact combination exists. When it doesn't, the other axes give way rather than the
 * click doing nothing: prefer an in-stock priced variant with the chosen value, then any
 * priced one, then any — mirroring `initialVariant`'s preference order.
 */
export function pickVariant(
  variants: Variant[],
  current: Record<string, string>,
  axis: string,
  value: string,
): Variant | null {
  const exact = matchVariant(variants, { ...current, [axis]: value });
  if (exact) return exact;
  const withValue = variants.filter((v) => optionValue(v, axis) === value);
  return (
    withValue.find((v) => v.in_stock && v.price !== null) ??
    withValue.find((v) => v.price !== null) ??
    withValue[0] ??
    null
  );
}
