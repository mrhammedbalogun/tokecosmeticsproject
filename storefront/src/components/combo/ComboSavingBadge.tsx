import { formatMoney } from "@/lib/country";
import type { ComboPricing } from "@/lib/combos";

/** "Save ₦2,000 · 10% off" — the one claim a bundle has to make, stated once.
 *
 * `saving_percent` comes from the API already worked out FROM THE TWO AMOUNTS, not from
 * a stored rate: a combo pinned at a price no longer equal to "10% off" must advertise
 * the discount it actually gives. Trailing zeros are trimmed so "10.00%" reads "10%". */
export function ComboSavingBadge({
  pricing,
  size = "md",
}: {
  pricing: ComboPricing;
  size?: "sm" | "md";
}) {
  const percent = String(Number(pricing.saving_percent));
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full bg-accent px-2.5 py-1 font-semibold text-white ${
        size === "sm" ? "text-[10px]" : "text-xs"
      }`}
    >
      <svg viewBox="0 0 16 16" aria-hidden="true" className="h-3 w-3 fill-current">
        <path d="M13.3 7.1 8.9 2.7a1.5 1.5 0 0 0-1-.4H4a1.5 1.5 0 0 0-1.5 1.5v3.9c0 .4.1.7.4 1l4.4 4.4a1.5 1.5 0 0 0 2.1 0l3.9-3.9a1.5 1.5 0 0 0 0-2.1ZM5.2 6a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z" />
      </svg>
      Save {formatMoney(pricing.saving, pricing.currency)}
      <span className="opacity-80">· {percent}% off</span>
    </span>
  );
}
