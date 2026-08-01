/**
 * The Variants tab: the variants this product already has.
 *
 * READ-MOSTLY BY DESIGN. This panel edits existing variants' stock through the adjust
 * modal and nothing else; GENERATING variants from an option matrix is the builder above
 * it, which shipped in 17b. That split exists because 26% of the production catalogue is
 * multi-variant — an editor that could not show existing variants would be unusable on a
 * quarter of the range.
 *
 * STOCK IS SHOWN, NEVER TYPED. `StockItemAdminViewSet` sets
 * `http_method_names = ["get", "post", "head", "options"]` — it refuses PUT and PATCH
 * outright, and the only route to a quantity is the `adjust` action, which requires a
 * reason and a note and writes a `StockMovement`. An editable number field here would be a
 * lie about what the API permits.
 *
 * PRESENTATIONAL: no state of its own.
 */
import type { StockRow } from "@/lib/product-stock";
import type { VariantRow } from "@/lib/product-prices";

export function VariantsPanel({
  variants,
  stock,
  warehouses,
  onAdjust,
}: {
  variants: VariantRow[];
  stock: StockRow[];
  /** Every warehouse that appears in `stock`, in a stable order. */
  warehouses: { id: number; name: string }[];
  /** Opens the adjust modal. */
  onAdjust?: (stockItemId: number) => void;
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
            <th scope="col" className="p-3 font-medium">Weight</th>
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
              <td className="p-3 tabular-nums">
                {/* BLANK, never "0 g". Eight production variants have no weight at all, and
                    a zero would be a claim about a parcel rather than an absence — it is
                    also the number a courier quote would be built from. */}
                {variant.weight_grams === null ? (
                  <span className="text-warn" title="No weight recorded">
                    —
                  </span>
                ) : (
                  `${variant.weight_grams} g`
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
