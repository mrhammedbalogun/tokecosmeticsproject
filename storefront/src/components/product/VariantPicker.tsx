"use client";
import type { Variant } from "@/lib/catalog";
import { usePdp } from "@/components/product/PdpContext";
import { variantLabel, variantLegend } from "@/lib/variant-label";

export function VariantPicker({ variants }: { variants: Variant[] }) {
  const { variant, setVariant } = usePdp();
  if (variants.length <= 1) return null;
  return (
    <fieldset className="mt-5">
      {/* Was hardcoded "Size". The axis is called `Product Size` on 55 production variants
          and `Price Options` on 43, and 8 products have both — so it is read from the data
          rather than asserted. */}
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
              {/* NOT `v.name`: on the 8 two-axis products that is the PRODUCT's name
                  repeated, so the picker offered seven identical buttons at seven
                  different prices. See lib/variant-label.ts. */}
              {variantLabel(v)}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}
