/**
 * The "For Who" tab: who the product is intended for — Male, Female, Baby.
 *
 * CHECKBOXES, NOT A RADIO: a product is routinely for more than one audience (a shea
 * butter for men and women, a gentle wash for women and babies), so this is a set.
 *
 * The data exists for FILTERING AND RECOMMENDATION — storefront filters and the AI
 * product-recommendation agent read it — not for display copy. Empty is a valid state
 * and means "not stated", not "for nobody"; the wording below says so, the same way the
 * Availability tab explains its own empty state.
 *
 * PRESENTATIONAL, like the other panels: no state of its own.
 */
import type { PanelProps } from "@/components/product/DetailsPanel";
import { AUDIENCES } from "@/lib/product-form";

export function ForWhoPanel({ values, errors, onChange }: PanelProps) {
  const toggle = (code: string) =>
    onChange(
      "audience",
      values.audience.includes(code)
        ? values.audience.filter((c) => c !== code)
        : [...values.audience, code],
    );

  return (
    <div className="max-w-xl">
      <fieldset>
        <legend className="text-xs text-muted">Who is this product for?</legend>
        <div className="mt-2 space-y-1 rounded border border-line bg-surface p-3">
          {AUDIENCES.map(({ code, label }) => (
            <label key={code} className="flex items-center gap-2 py-0.5 text-sm">
              <input
                type="checkbox"
                checked={values.audience.includes(code)}
                onChange={() => toggle(code)}
                className="h-4 w-4 rounded border-line"
              />
              {label}
            </label>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted">
          {values.audience.length === 0
            ? "Nothing selected — the product simply is not labelled for anyone in particular. Tick every audience it suits; more than one is fine."
            : "Used for storefront filtering and product recommendations."}
        </p>
        {errors.audience && <p className="mt-1 text-xs text-warn">{errors.audience}</p>}
      </fieldset>
    </div>
  );
}
