/**
 * The shared deliveries-table bones (Plan-35 ruling 5): columns + rows in, a table out.
 *
 * CARRIER-NEUTRAL ON PURPOSE — no GIG imports here. `/deliveries/gig` composes it
 * today; an AAJ page composes the same component over its own shipment model when that
 * integration lands. A Server Component like OrderTable: every cell is static and the
 * only control is whatever link the caller put in a cell, so nothing hydrates.
 *
 * THE TABLE READS; THE ORDER PAGE ACTS (ruling 4): no action buttons belong in a cell.
 * Capture is a money-moving act with its own confirm ritual on the order page, and a
 * bulk surface that can dispatch a rider on a mis-click is not a feature.
 */
import type { ReactNode } from "react";

export interface ShipmentColumn {
  key: string;
  label: string;
  align?: "right";
}

export interface ShipmentTableRow {
  /** React key — the order number is the natural choice. */
  id: string;
  cells: Record<string, ReactNode>;
}

export function CarrierShipmentTable({
  columns,
  rows,
  emptyText,
}: {
  columns: ShipmentColumn[];
  rows: ShipmentTableRow[];
  emptyText: string;
}) {
  if (!rows.length) {
    return (
      <p className="rounded-[var(--radius-card)] border border-line bg-surface p-6 text-center text-sm text-muted">
        {emptyText}
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-line bg-surface text-left text-xs text-muted">
            {columns.map((column) => (
              <th
                scope="col"
                key={column.key}
                className={`p-3 font-medium ${column.align === "right" ? "text-right" : ""}`}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b border-line last:border-0">
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={`p-3 align-top ${column.align === "right" ? "text-right" : ""}`}
                >
                  {row.cells[column.key] ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
