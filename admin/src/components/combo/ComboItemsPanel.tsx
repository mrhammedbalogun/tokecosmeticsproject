"use client";

/**
 * What is in the box: the picked variants, their quantities, and what each contributes.
 *
 * Presentational — the editor owns the list. The per-row contribution is shown in the
 * builder's home market only; the full per-market picture is the pricing panel's job, and
 * repeating four currencies on every row would bury the thing this list is for, which is
 * "is this the right box".
 */
import { Thumb } from "@/components/combo/ProductPicker";
import { optionSummary, roundHalfUp, type ComboItemRow } from "@/lib/combos";

export function ComboItemsPanel({
  items,
  market,
  currencySymbol,
  onQuantity,
  onRemove,
  onMove,
}: {
  items: ComboItemRow[];
  market: string;
  currencySymbol: string;
  onQuantity: (variantId: number, quantity: number) => void;
  onRemove: (variantId: number) => void;
  onMove: (variantId: number, direction: -1 | 1) => void;
}) {
  if (!items.length) {
    return (
      <p className="rounded-[var(--radius-card)] border border-dashed border-line bg-surface p-6 text-center text-sm text-muted">
        Nothing in this combo yet. Search above to add the first product.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {items.map((item, index) => {
        const unit = item.prices[market];
        const line = unit == null ? null : roundHalfUp(Number(unit) * item.quantity);
        return (
          <li
            key={item.variant}
            className="flex items-center gap-3 rounded-[var(--radius-card)] border border-line bg-surface p-3"
          >
            <Thumb src={item.image} alt="" size={48} />

            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{item.product_name}</p>
              <p className="truncate text-xs text-muted">
                {optionSummary(item.option_values, item.variant_name)}
                <span className="ml-2 font-mono text-[11px]">{item.sku}</span>
              </p>
              {unit == null && (
                <p className="mt-1 text-xs text-warn">
                  No price in {market} — the combo cannot be sold there until this variant
                  has one.
                </p>
              )}
            </div>

            <label className="flex items-center gap-1.5 text-xs text-muted">
              <span className="sr-only sm:not-sr-only">Qty</span>
              <input
                type="number"
                min={1}
                value={item.quantity}
                onChange={(e) => onQuantity(item.variant, Math.max(1, Number(e.target.value) || 1))}
                className="w-16 rounded border border-line bg-background px-2 py-1 text-right text-sm tabular-nums focus:border-accent focus:outline-none"
              />
            </label>

            <span className="w-24 shrink-0 text-right text-sm tabular-nums">
              {line == null
                ? "—"
                : `${currencySymbol}${line.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
            </span>

            <div className="flex shrink-0 flex-col">
              <button
                type="button"
                onClick={() => onMove(item.variant, -1)}
                disabled={index === 0}
                aria-label={`Move ${item.product_name} up`}
                className="px-1 text-xs text-muted hover:text-foreground disabled:opacity-25"
              >
                ▲
              </button>
              <button
                type="button"
                onClick={() => onMove(item.variant, 1)}
                disabled={index === items.length - 1}
                aria-label={`Move ${item.product_name} down`}
                className="px-1 text-xs text-muted hover:text-foreground disabled:opacity-25"
              >
                ▼
              </button>
            </div>

            <button
              type="button"
              onClick={() => onRemove(item.variant)}
              aria-label={`Remove ${item.product_name}`}
              className="shrink-0 rounded px-2 py-1 text-xs text-muted hover:bg-warn/10 hover:text-warn"
            >
              Remove
            </button>
          </li>
        );
      })}
    </ul>
  );
}
