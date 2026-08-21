/**
 * The partner deliveries filter bar — GigShipmentFilterForm's sibling: a PLAIN GET
 * FORM and a Server Component, so submitting navigates to the URL shape the page
 * already reads.
 *
 * Status is the ORDER vocabulary (a partner shipment has no lifecycle of its own),
 * and "Partner delivered" filters the machine stamp instead — that pair is what
 * answers "what should the partner invoice us?": delivered=yes keeps rows a later
 * refund re-statused, which the status select alone would lose.
 */
import Link from "next/link";
import type { PartnerShipmentFilters } from "@/lib/deliveries";
import { ORDER_STATUSES, statusLabel } from "@/lib/orders";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none";

export function PartnerShipmentFilterForm({
  filters,
  basePath,
}: {
  filters: PartnerShipmentFilters;
  /** The page's own route — where Clear returns to. */
  basePath: string;
}) {
  return (
    <form
      method="get"
      className="mb-4 grid gap-3 rounded-[var(--radius-card)] border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4"
    >
      <label className="block text-xs text-muted">
        Order status
        <select name="status" defaultValue={filters.status ?? ""} className={`mt-1 ${FIELD}`}>
          <option value="">Any</option>
          {ORDER_STATUSES.map((status) => (
            <option key={status} value={status}>
              {statusLabel(status)}
            </option>
          ))}
        </select>
      </label>

      <label className="block text-xs text-muted">
        Partner delivered
        <select
          name="delivered"
          defaultValue={filters.delivered ?? ""}
          className={`mt-1 ${FIELD}`}
        >
          <option value="">Any</option>
          <option value="yes">Delivered</option>
          <option value="no">Not delivered</option>
        </select>
      </label>

      <label className="block text-xs text-muted">
        Placed after
        <input
          type="date"
          name="placed_after"
          defaultValue={filters.placed_after ?? ""}
          className={`mt-1 ${FIELD}`}
        />
      </label>

      <label className="block text-xs text-muted">
        Placed before
        <input
          type="date"
          name="placed_before"
          defaultValue={filters.placed_before ?? ""}
          className={`mt-1 ${FIELD}`}
        />
      </label>

      <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-4">
        <button
          type="submit"
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
        >
          Filter
        </button>
        <Link
          href={basePath}
          className="rounded border border-line px-3 py-1.5 text-sm hover:bg-surface"
        >
          Clear
        </Link>
      </div>
    </form>
  );
}
