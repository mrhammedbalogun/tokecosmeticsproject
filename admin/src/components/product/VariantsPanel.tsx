/**
 * The Variants tab: the variants this product already has.
 *
 * READ-MOSTLY BY DESIGN. This panel edits existing variants' stock through the adjust
 * modal, and — since weights became editable — their `weight_grams`; GENERATING variants
 * from an option matrix is the builder above it, which shipped in 17b. That split exists
 * because 26% of the production catalogue is multi-variant — an editor that could not
 * show existing variants would be unusable on a quarter of the range.
 *
 * STOCK IS SHOWN, NEVER TYPED. `StockItemAdminViewSet` sets
 * `http_method_names = ["get", "post", "head", "options"]` — it refuses PUT and PATCH
 * outright, and the only route to a quantity is the `adjust` action, which requires a
 * reason and a note and writes a `StockMovement`. An editable number field here would be a
 * lie about what the API permits.
 *
 * WEIGHT IS TYPED, and that is not the same lie: `ProductVariantAdminViewSet` PATCHes
 * `weight_grams` like any other field, delivery quotes are priced from it
 * (apps/delivery/services.py), and 8 production variants arrived from WooCommerce with
 * none — this input is how those get fixed. Commit on blur, like the price grid; each
 * write lands immediately (no relation to the product form's Save).
 *
 * PRESENTATIONAL: no state of its own — drafts and errors live in `ProductEditor`,
 * because this panel unmounts on every tab switch.
 */
import type { StockRow } from "@/lib/product-stock";
import type { VariantRow } from "@/lib/product-prices";

export function VariantsPanel({
  variants,
  stock,
  warehouses,
  onAdjust,
  weightDrafts,
  weightErrors,
  weightBusyId,
  onWeightDraft,
  onWeightCommit,
}: {
  variants: VariantRow[];
  stock: StockRow[];
  /** Every warehouse that appears in `stock`, in a stable order. */
  warehouses: { id: number; name: string }[];
  /** Opens the adjust modal. */
  onAdjust?: (stockItemId: number) => void;
  /** In-progress weight text, keyed by variant id; absent = show the stored value. */
  weightDrafts: Record<number, string>;
  weightErrors: Record<number, string>;
  /** The variant whose weight is being written right now, if any. */
  weightBusyId: number | null;
  onWeightDraft: (variantId: number, text: string) => void;
  onWeightCommit: (variantId: number) => void;
}) {
  if (!variants.length) {
    return (
      <p className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center text-sm text-muted">
        This product has no variants yet. Add an option above to generate them.
      </p>
    );
  }

  const cell = (variantId: number, warehouseId: number) =>
    stock.find((s) => s.variant === variantId && s.warehouse === warehouseId);

  return (
    <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-line bg-surface text-left text-xs text-muted">
            <th scope="col" className="p-3 font-medium">SKU</th>
            <th scope="col" className="p-3 font-medium">Name</th>
            <th scope="col" className="p-3 font-medium">Weight (g)</th>
            {warehouses.map((warehouse) => (
              <th key={warehouse.id} scope="col" className="p-3 font-medium">
                {warehouse.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {variants.map((variant) => (
            <tr key={variant.id} className="border-b border-line last:border-0">
              <td className="p-3 font-mono text-xs">{variant.sku}</td>
              <td className="p-3">
                {variant.name}
                {!variant.is_active && (
                  <span className="ml-2 rounded border border-line px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted">
                    Inactive
                  </span>
                )}
              </td>
              <td className="p-3">
                <span className="flex items-center gap-2">
                  <input
                    type="text"
                    inputMode="numeric"
                    // BLANK, never "0". Eight production variants have no weight at
                    // all, and a zero would be a claim about a parcel rather than an
                    // absence — it is also the number a courier quote would be built
                    // from. Blank + the warning border says "not recorded" honestly.
                    value={weightDrafts[variant.id] ?? (variant.weight_grams === null ? "" : String(variant.weight_grams))}
                    onChange={(e) => onWeightDraft(variant.id, e.target.value)}
                    onBlur={() => onWeightCommit(variant.id)}
                    onKeyDown={(e) => {
                      // Enter commits, like every grid in this editor. The blur it
                      // causes is a no-op: commit clears the draft, so the second
                      // call finds nothing typed.
                      if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                    }}
                    disabled={weightBusyId === variant.id}
                    aria-label={`Weight in grams for ${variant.sku}`}
                    placeholder="—"
                    title={variant.weight_grams === null && weightDrafts[variant.id] === undefined ? "No weight recorded — delivery quotes treat it as 0 g" : undefined}
                    className={`w-24 rounded border bg-surface px-2 py-1 text-right text-sm tabular-nums focus:outline-none ${
                      weightErrors[variant.id]
                        ? "border-warn"
                        : variant.weight_grams === null && weightDrafts[variant.id] === undefined
                          ? "border-warn/50"
                          : "border-line focus:border-accent"
                    }`}
                  />
                  {weightBusyId === variant.id && <span className="text-xs text-muted">Saving…</span>}
                </span>
                {weightErrors[variant.id] && (
                  <p className="mt-1 text-xs text-warn">{weightErrors[variant.id]}</p>
                )}
              </td>
              {warehouses.map((warehouse) => {
                const item = cell(variant.id, warehouse.id);
                return (
                  <td key={warehouse.id} className="p-3">
                    {item ? (
                      <span className="flex items-center gap-2">
                        <span className="tabular-nums">{item.quantity}</span>
                        {item.reserved > 0 && (
                          <span className="text-xs text-muted" title="Held by pending checkouts">
                            ({item.reserved} held)
                          </span>
                        )}
                        <button
                          type="button"
                          onClick={() => onAdjust?.(item.id)}
                          disabled={!onAdjust}
                          className="rounded border border-line px-2 py-0.5 text-xs text-muted hover:border-accent hover:text-fg disabled:opacity-40"
                        >
                          Adjust
                        </button>
                      </span>
                    ) : (
                      // Not zero: production has one stock row per variant, so "no row in
                      // this warehouse" is the common case and means something different
                      // from "none in stock here".
                      <span className="text-xs text-muted" title="No stock record here">
                        —
                      </span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
