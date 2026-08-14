/**
 * The deliveries-table filter bar. A PLAIN GET FORM and a Server Component, matching
 * `OrderFilterForm`: submitting navigates to `?origin=…&status=…`, the URL shape the
 * page already reads — bookmarkable, survives a reload, back button undoes a filter.
 *
 * The origin select is the packing-desk control this page exists for: "what must MY
 * shop pack today?". Choices come from `/admin/sender-locations/` plus the built-in
 * id-0 entry (pre-Plan-34 shipments and the env fallback carry an empty snapshot, and
 * they must not vanish from a filtered view).
 */
import Link from "next/link";
import { SHIPMENT_STATUSES, type GigShipmentFilters } from "@/lib/deliveries";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none";

export function GigShipmentFilterForm({
  filters,
  origins,
}: {
  filters: GigShipmentFilters;
  /** Sender locations for the origin filter, id 0 included. Empty when the visitor's
   *  role cannot list them (Support) — the control hides rather than lying. */
  origins: { id: number; name: string }[];
}) {
  return (
    <form
      method="get"
      className="mb-4 grid gap-3 rounded-[var(--radius-card)] border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-5"
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
          {SHIPMENT_STATUSES.map((status) => (
            <option key={status} value={status}>
              {status.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </label>

      <label className="block text-xs text-muted">
        Service
        <select name="service" defaultValue={filters.service ?? ""} className={`mt-1 ${FIELD}`}>
          <option value="">Any</option>
          <option value="door">Door delivery</option>
          <option value="pickup">Centre pickup</option>
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

      <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-5">
        <button
          type="submit"
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
        >
          Filter
        </button>
        <Link
          href="/deliveries/gig"
          className="rounded border border-line px-3 py-1.5 text-sm hover:bg-surface"
        >
          Clear
        </Link>
      </div>
    </form>
  );
}
