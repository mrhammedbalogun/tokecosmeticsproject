/**
 * The Prices tab: a variant × currency grid.
 *
 * WRITES IMMEDIATELY, per cell, like images — prices are their own resource and are not
 * part of the product's Save (17a design decision 1). The notice at the top says so.
 *
 * LOCKED CELLS ARE SHOWN, NOT HIDDEN. Where a country override or a scheduled row exists
 * for a variant+currency, the cell is read-only and says which. Hiding that and letting
 * somebody edit the plain row underneath would be an edit that appears to succeed and
 * changes nothing a customer sees — see `lib/product-prices.ts` for the full argument.
 *
 * PRESENTATIONAL: the grid, the drafts and the busy state live in `ProductEditor`, because
 * this panel unmounts on every tab switch.
 */
import type { Cell, GridRow } from "@/lib/product-prices";

const INPUT =
  "w-28 rounded border border-line bg-surface px-2 py-1 text-sm tabular-nums focus:border-accent focus:outline-none";

export interface PricesPanelProps {
  grid: GridRow[];
  currencies: readonly string[];
  drafts: Record<string, string>;
  errors: Record<string, string>;
  busyKey: string | null;
  onDraft: (key: string, value: string) => void;
  onCommit: (variantId: number, currency: string, cell: Cell) => void;
}

export const cellKey = (variantId: number, currency: string) => `${variantId}:${currency}`;

export function PricesPanel({
  grid,
  currencies,
  drafts,
  errors,
  busyKey,
  onDraft,
  onCommit,
}: PricesPanelProps) {
  if (!grid.length) {
    return (
      <p className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center text-sm text-muted">
        This product has no variants, so there is nothing to price yet.
      </p>
    );
  }

  return (
    <div>
      <p className="rounded-[var(--radius-card)] border border-accent/30 bg-accent/10 p-3 text-sm">
        Prices save <strong>as you leave each box</strong> — they are not part of Save.
      </p>

      <div className="mt-4 overflow-x-auto rounded-[var(--radius-card)] border border-line">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-line bg-surface text-left text-xs text-muted">
              <th scope="col" className="p-3 font-medium">Variant</th>
              {currencies.map((currency) => (
                <th key={currency} scope="col" className="p-3 font-medium">
                  {currency}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.map((row) => (
              <tr key={row.variant.id} className="border-b border-line last:border-0 align-top">
                <td className="p-3">
                  <div>{row.variant.name}</div>
                  <div className="font-mono text-xs text-muted">{row.variant.sku}</div>
                </td>

                {currencies.map((currency) => {
                  const cell = row.cells[currency];
                  const key = cellKey(row.variant.id, currency);
                  const label = `${row.variant.sku} price in ${currency}`;

                  if (cell.state === "locked") {
                    return (
                      <td key={currency} className="p-3">
                        <input
                          type="text"
                          value={cell.amount || "—"}
                          readOnly
                          aria-label={label}
                          className={`${INPUT} cursor-not-allowed opacity-60`}
                        />
                        <p className="mt-1 max-w-56 text-xs text-warn">{cell.reason}</p>
                      </td>
                    );
                  }

                  const draft = drafts[key] ?? cell.amount;
                  const error = errors[key];
                  return (
                    <td key={currency} className="p-3">
                      <input
                        type="text"
                        inputMode="decimal"
                        value={draft}
                        onChange={(e) => onDraft(key, e.target.value)}
                        onBlur={() => onCommit(row.variant.id, currency, cell)}
                        disabled={busyKey === key}
                        placeholder="—"
                        aria-label={label}
                        className={`${INPUT} ${
                          error ? "border-warn" : !cell.price ? "border-warn/40" : ""
                        }`}
                      />
                      {error ? (
                        <p className="mt-1 max-w-56 text-xs text-warn">{error}</p>
                      ) : (
                        !cell.price && (
                          // Flagged rather than left blank: an unpriced currency is why a
                          // product is invisible in that market, and production is
                          // NGN-only, so this is most of the grid today.
                          <p className="mt-1 text-xs text-muted">Not priced</p>
                        )
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-xs text-muted">
        A market needs a price in its currency before the product appears there at all.
        Country-specific and scheduled prices cannot be edited here.
      </p>
    </div>
  );
}
