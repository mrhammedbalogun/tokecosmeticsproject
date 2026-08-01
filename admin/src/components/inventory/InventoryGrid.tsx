"use client";

/**
 * The inventory grid: variant per row, active warehouse per column.
 *
 * ── AN EMPTY CELL IS THE POINT, NOT A GAP IN THE TABLE ──────────────────────────────
 *
 * Plan-17c ruling 3. Production holds 122 stock rows against 244 possible cells and every
 * empty one is the UK Warehouse — an absence that showed up on no other screen, because
 * every other screen lists stock ROWS and an absent row has nothing to list. So a cell
 * with no `StockItem` renders as a legible "not stocked", never as a blank and never as
 * `0`. Zero means somebody counted and found none; absent means nobody has ever counted.
 *
 * Creating the missing row is Plan-17c Task 4. Until then the absence is visible and
 * honest about being unfixable from here, which is better than being invisible.
 *
 * The Adjust modal is 17a Task 7's, reused unchanged — it already knows that the quantity
 * is an absolute count rather than a delta, and that a reason and a note are required.
 */
import { useState, useTransition } from "react";
import { StockAdjustModal } from "@/components/product/StockAdjustModal";
import { adjustStockAction } from "@/app/(shell)/inventory/actions";
import { cellState, rowTotal, type GridCell, type GridRow, type WarehouseColumn } from "@/lib/inventory";
import type { AdjustErrors } from "@/lib/stock-adjust";

interface OpenCell {
  row: GridRow;
  cell: GridCell;
}

export function InventoryGrid({
  rows,
  warehouses,
}: {
  rows: GridRow[];
  warehouses: WarehouseColumn[];
}) {
  const [open, setOpen] = useState<OpenCell | null>(null);
  const [errors, setErrors] = useState<AdjustErrors>({});
  const [message, setMessage] = useState<string | null>(null);
  const [busy, startTransition] = useTransition();

  if (!rows.length) {
    return (
      <p className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center text-sm text-muted">
        No variants match this filter.
      </p>
    );
  }

  const close = () => {
    setOpen(null);
    setErrors({});
    setMessage(null);
  };

  const submit = (values: { quantity: number; reason: string; note: string }) => {
    if (!open?.cell.stock_item_id) return;
    setErrors({});
    setMessage(null);
    startTransition(async () => {
      const state = await adjustStockAction({
        stockItemId: open.cell.stock_item_id as number,
        ...values,
      });
      if (state.ok) close();
      else {
        setErrors(state.errors ?? {});
        setMessage(state.message ?? null);
      }
    });
  };

  return (
    <>
      <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line">
        <table className="w-full min-w-[40rem] text-sm">
          <thead className="bg-surface text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Variant</th>
              {warehouses.map((warehouse) => (
                <th key={warehouse.id} className="px-3 py-2 text-left font-medium">
                  {warehouse.name}
                </th>
              ))}
              <th className="px-3 py-2 text-right font-medium">Total</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const total = rowTotal(row);
              return (
                <tr key={row.variant_id} className="border-t border-line">
                  <td className="px-3 py-2">
                    <div>{row.product_name}</div>
                    <div className="text-xs text-muted">
                      <span className="font-mono">{row.sku}</span>
                      {row.variant_name ? ` · ${row.variant_name}` : ""}
                    </div>
                  </td>
                  {row.cells.map((cell) => (
                    <td key={cell.warehouse_id} className="px-3 py-2">
                      <Cell
                        cell={cell}
                        onAdjust={() => {
                          setErrors({});
                          setMessage(null);
                          setOpen({ row, cell });
                        }}
                      />
                    </td>
                  ))}
                  <td className="px-3 py-2 text-right tabular-nums">
                    {/* Nothing counted anywhere prints an em dash, not 0: a total of zero
                        would assert a count that never happened. */}
                    {total === null ? <span className="text-muted">—</span> : total}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {open?.cell.stock_item_id != null && (
        <StockAdjustModal
          sku={open.row.sku}
          warehouseName={open.cell.warehouse_name}
          currentQuantity={open.cell.quantity ?? 0}
          reserved={open.cell.reserved ?? 0}
          busy={busy}
          serverErrors={errors}
          serverMessage={message}
          onSubmit={submit}
          onClose={close}
        />
      )}
    </>
  );
}

function Cell({ cell, onAdjust }: { cell: GridCell; onAdjust: () => void }) {
  const state = cellState(cell);

  if (state === "absent") {
    return (
      <span
        className="inline-flex items-center gap-1 rounded border border-dashed border-line px-1.5 py-0.5 text-xs text-muted"
        title="No stock row here. Nobody has counted this variant in this warehouse."
      >
        Not stocked
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={onAdjust}
      className={`inline-flex items-center gap-2 rounded px-1.5 py-0.5 text-left hover:bg-surface ${
        state === "low" ? "text-warn" : ""
      }`}
      title="Adjust this count"
    >
      <span className="tabular-nums">{cell.quantity}</span>
      {cell.reserved ? (
        <span className="text-xs text-muted">({cell.reserved} held)</span>
      ) : null}
      {state === "low" && (
        <span className="rounded border border-warn/40 px-1 text-[10px] uppercase tracking-wide">
          Low
        </span>
      )}
    </button>
  );
}
