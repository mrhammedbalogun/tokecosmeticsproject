/**
 * The orders table.
 *
 * A Server Component — every row is static and the only control is a link, so nothing is
 * handed to a Client Component and no row data reaches the browser beyond what renders
 * (the Plan-16 Task 8 lesson about RSC payloads).
 *
 * THE FLAG IS SHOWN ON THE ROW, not hidden behind the needs-attention filter. Every
 * `review_reason` is a money discrepancy and four of the five say "refund" — an operator
 * scanning the queue should see which orders are wrong without first knowing to go and
 * look for them.
 */
import Link from "next/link";
import { OPEN_STATUSES, reviewReasons, statusLabel, type OrderRow } from "@/lib/orders";

const STATUS_STYLE: Record<string, string> = {
  pending_payment: "border-warn/30 bg-warn/5 text-warn",
  processing: "border-accent/30 bg-accent/10 text-accent",
  shipped: "border-accent/30 bg-accent/10 text-accent",
  delivered: "border-ok/30 bg-ok/10 text-ok",
  completed: "border-ok/30 bg-ok/10 text-ok",
  on_hold: "border-warn/30 bg-warn/5 text-warn",
  expired: "border-line bg-surface text-muted",
  cancelled: "border-line bg-surface text-muted",
  refunded: "border-line bg-surface text-muted",
};

export function OrderTable({ rows }: { rows: OrderRow[] }) {
  if (!rows.length) {
    return (
      <p className="rounded-[var(--radius-card)] border border-line bg-surface p-6 text-center text-sm text-muted">
        No orders match those filters.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-line bg-surface text-left text-xs text-muted">
            <th scope="col" className="p-3 font-medium">Order</th>
            <th scope="col" className="p-3 font-medium">Placed</th>
            <th scope="col" className="p-3 font-medium">Customer</th>
            <th scope="col" className="p-3 font-medium">Status</th>
            <th scope="col" className="p-3 font-medium text-right">Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const reasons = reviewReasons(row);
            return (
              <tr
                key={row.number}
                className={`border-b border-line last:border-0 ${
                  reasons.length ? "bg-warn/5" : ""
                }`}
              >
                <td className="p-3 align-top">
                  <Link
                    href={`/orders/${row.number}`}
                    className="font-mono font-medium underline-offset-2 hover:underline"
                  >
                    {row.number}
                  </Link>
                  {row.source && row.source !== "web" && (
                    <div className="text-xs text-muted">{row.source}</div>
                  )}
                </td>

                <td className="p-3 align-top text-xs text-muted">
                  {/* ISO, not `toLocaleDateString`: this renders on the server, so a
                      locale-formatted date would be the SERVER's locale presented as the
                      reader's — which is how 03/04 becomes ambiguous. */}
                  {row.placed_at ? row.placed_at.slice(0, 10) : "—"}
                </td>

                <td className="p-3 align-top">
                  <div className="truncate">{row.email || "—"}</div>
                  <div className="text-xs text-muted">{row.country}</div>
                </td>

                <td className="p-3 align-top">
                  <span
                    className={`rounded border px-2 py-0.5 text-xs ${
                      STATUS_STYLE[row.status] ?? "border-line bg-surface text-muted"
                    }`}
                  >
                    {statusLabel(row.status)}
                  </span>
                  {!OPEN_STATUSES.includes(row.status) && reasons.length === 0 && null}

                  {reasons.length > 0 && (
                    <ul className="mt-1 max-w-md space-y-0.5">
                      {reasons.map((reason) => (
                        // Displayed verbatim. These are human sentences written by
                        // payments/services.py with amounts baked in; anything that
                        // parsed them would break the first time one is reworded.
                        <li key={reason} className="text-xs text-warn">
                          {reason}
                        </li>
                      ))}
                    </ul>
                  )}
                </td>

                <td className="p-3 align-top text-right tabular-nums">
                  {row.grand_total_display}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
