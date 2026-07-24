"use client";
import type { Variant } from "@/lib/catalog";
import { usePdp } from "@/components/product/PdpContext";

export function VariantPicker({ variants }: { variants: Variant[] }) {
  const { variant, setVariant } = usePdp();
  if (variants.length <= 1) return null;
  return (
    <fieldset className="mt-5">
      <legend className="text-sm font-medium">Size</legend>
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
              {v.name}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}
