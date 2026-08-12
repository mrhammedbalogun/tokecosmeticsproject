"use client";
import type { Variant } from "@/lib/catalog";
import { usePdp } from "@/components/product/PdpContext";
import { variantLabel, variantLegend } from "@/lib/variant-label";
import { pickVariant, variantAxes, type VariantAxis } from "@/lib/variant-axes";

export function VariantPicker({ variants }: { variants: Variant[] }) {
  if (variants.length <= 1) return null;
  const axes = variantAxes(variants);
  /* One axis → pills: the values are few and short, and seeing them all at once beats a
     dropdown. Two or more axes → one dropdown per axis, otherwise the pills enumerate the
     full cross-product ("1l · red" × 12) instead of letting the shopper pick a size and a
     colour independently. */
  if (axes.length >= 2) return <AxisSelects variants={variants} axes={axes} />;
  return <PillPicker variants={variants} />;
}

function AxisSelects({ variants, axes }: { variants: Variant[]; axes: VariantAxis[] }) {
  const { variant, setVariant } = usePdp();
  const current: Record<string, string> = {};
  for (const [axis, value] of Object.entries(variant?.option_values ?? {})) {
    const trimmed = String(value).trim();
    if (trimmed) current[axis] = trimmed;
  }
  return (
    <div className="mt-5 flex flex-wrap gap-4">
      {axes.map((axis) => (
        <label key={axis.name} className="min-w-40 flex-1 text-sm font-medium">
          Choose {axis.name}
          <select
            value={current[axis.name] ?? ""}
            onChange={(e) => {
              const next = pickVariant(variants, current, axis.name, e.target.value);
              if (next) setVariant(next);
            }}
            className="mt-2 block w-full rounded-lg border border-line bg-surface px-3 py-2.5 text-sm font-normal transition focus:border-accent focus:outline-none"
          >
            {current[axis.name] === undefined && (
              <option value="" disabled hidden>
                Select {axis.name.toLowerCase()}
              </option>
            )}
            {axis.values.map((value) => {
              /* Annotate each choice with where it would land, so "out of stock" is
                 visible before selecting — the dropdown equivalent of the pills'
                 line-through. `disabled` only when unpriced (unavailable in region),
                 matching the pills; out-of-stock stays selectable so the buy box can
                 explain. */
              const target = pickVariant(variants, current, axis.name, value);
              const unpriced = !target || target.price === null;
              return (
                <option key={value} value={value} disabled={unpriced}>
                  {value}
                  {unpriced ? " — unavailable" : !target.in_stock ? " — out of stock" : ""}
                </option>
              );
            })}
          </select>
        </label>
      ))}
    </div>
  );
}

function PillPicker({ variants }: { variants: Variant[] }) {
  const { variant, setVariant } = usePdp();
  return (
    <fieldset className="mt-5">
      {/* Was hardcoded "Size". The axis is called `Product Size` on 55 production variants
          and `Price Options` on 43 — so it is read from the data rather than asserted. */}
      <legend className="text-sm font-medium">{variantLegend(variants)}</legend>
      <div className="mt-2 flex flex-wrap gap-2">
        {variants.map((v) => {
          const selected = variant?.id === v.id;
          const disabled = v.price === null;
          return (
            <button key={v.id} type="button" onClick={() => setVariant(v)} disabled={disabled}
              aria-pressed={selected}
              className={`rounded-full border px-4 py-2 text-sm transition
                ${selected ? "border-accent bg-accent text-surface" : "border-line hover:border-accent"}
                ${disabled ? "cursor-not-allowed opacity-40" : ""}
                ${!v.in_stock && !disabled ? "line-through" : ""}`}>
              {/* NOT `v.name`: on two-axis products that is the PRODUCT's name repeated,
                  so the picker offered seven identical buttons at seven different prices.
                  See lib/variant-label.ts. */}
              {variantLabel(v)}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}
