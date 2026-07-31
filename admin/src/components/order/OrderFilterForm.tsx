/**
 * The orders search and filter bar.
 *
 * A PLAIN GET FORM and a Server Component, matching `AuditFilterForm` and
 * `ProductFilterForm`: submitting navigates to `?search=…&gateway=…`, which is the URL
 * shape the page already reads. Bookmarkable, survives a reload, back button undoes a
 * filter.
 *
 * The status and needs-attention controls are NOT here — they are links in
 * `OrderStatusTabs`, so that switching queue does not require submitting a form. Both
 * write the same query string.
 */
import Link from "next/link";
import type { OrderFilters } from "@/lib/orders";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none";

export function OrderFilterForm({
  filters,
  countries,
  gateways,
}: {
  filters: OrderFilters;
  countries: { code: string; name: string }[];
  /** Gateways seen on this page of orders. See the page for why they are derived. */
  gateways: string[];
}) {
  return (
    <form
      method="get"
      className="mb-4 grid gap-3 rounded-[var(--radius-card)] border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-5"
    >
      {/* The status and needs-attention filters live in the tabs above. Carried through
          as hidden fields so submitting this form narrows the queue you are looking at
          rather than silently throwing you back to All. */}
      {filters.status && <input type="hidden" name="status" value={filters.status} />}
      {filters.needs_attention && <input type="hidden" name="needs_attention" value="true" />}

      <label className="block text-xs text-muted lg:col-span-2">
        Search
        <input
          type="search"
          name="search"
          defaultValue={filters.search ?? ""}
          placeholder="order number, email or address…"
          className={`mt-1 ${FIELD}`}
        />
      </label>

      <label className="block text-xs text-muted">
        Country
        <select name="country" defaultValue={filters.country ?? ""} className={`mt-1 ${FIELD}`}>
          <option value="">Any</option>
          {countries.map((country) => (
            <option key={country.code} value={country.code}>
              {country.name}
            </option>
          ))}
        </select>
      </label>

      <label className="block text-xs text-muted">
        Gateway
        <select name="gateway" defaultValue={filters.gateway ?? ""} className={`mt-1 ${FIELD}`}>
          <option value="">Any</option>
          {gateways.map((gateway) => (
            <option key={gateway} value={gateway}>
              {gateway.replace(/_/g, " ")}
            </option>
          ))}
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
          Apply
        </button>
        {/* A link, not `type="reset"`: reset restores the fields to what the page was
            rendered with, which on a filtered page is the filter itself. */}
        <Link href="/orders" className="text-sm text-muted underline-offset-2 hover:underline">
          Clear
        </Link>
      </div>
    </form>
  );
}
