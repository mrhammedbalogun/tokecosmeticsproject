/**
 * The AAJ deliveries-table filter bar (Plan-43) — GigShipmentFilterForm minus the
 * service select (AAJ is door delivery only). A plain GET form, bookmarkable.
 */
import Link from "next/link";
import { AAJ_SHIPMENT_STATUSES, type AajShipmentFilters } from "@/lib/deliveries";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none";

export function AajShipmentFilterForm({
  filters,
  origins,
}: {
  filters: AajShipmentFilters;
  origins: { id: number; name: string }[];
}) {
  return (
    <form
      method="get"
      className="mb-4 grid gap-3 rounded-[var(--radius-card)] border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4"
    >
      {origins.length > 0 && (
        <label className="block text-xs text-muted">
          Collecting from
          <select name="origin" defaultValue={filters.origin ?? ""} className={`mt-1 ${FIELD}`}>
            <option value="">Any origin</option>
            {origins.map((origin) => (
              <option key={origin.id} value={String(origin.id)}>
                {origin.name}
              </option>
            ))}
          </select>
        </label>
      )}

      <label className="block text-xs text-muted">
        Status
        <select name="status" defaultValue={filters.status ?? ""} className={`mt-1 ${FIELD}`}>
          <option value="">Any</option>
          {AAJ_SHIPMENT_STATUSES.map((status) => (
            <option key={status} value={status}>
              {status.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </label>

      <label className="block text-xs text-muted">
        Placed after
        <input type="date" name="placed_after" defaultValue={filters.placed_after ?? ""} className={`mt-1 ${FIELD}`} />
      </label>

      <label className="block text-xs text-muted">
        Placed before
        <input type="date" name="placed_before" defaultValue={filters.placed_before ?? ""} className={`mt-1 ${FIELD}`} />
      </label>

      <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-4">
        <button type="submit" className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90">
          Filter
        </button>
        <Link href="/deliveries/aaj" className="rounded border border-line px-3 py-1.5 text-sm hover:bg-surface">
          Clear
        </Link>
      </div>
    </form>
  );
}
