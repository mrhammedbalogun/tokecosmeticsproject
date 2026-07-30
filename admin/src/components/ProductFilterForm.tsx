/**
 * The products list's search box and status facet.
 *
 * A PLAIN GET FORM, and a Server Component — same reasoning as `AuditFilterForm`. No
 * `"use client"`, no state: submitting navigates to `?search=…&status=…`, which is the URL
 * shape the page already reads. Bookmarkable, survives a reload, and the back button
 * undoes a filter. A state-driven version would have to re-implement all three.
 *
 * `defaultValue` rather than `value`: uncontrolled, so the browser owns the field between
 * renders and the URL owns it across navigations.
 *
 * `page` is deliberately NOT a hidden field. Changing a filter must return to page 1 —
 * keeping page 3 while narrowing the results is how somebody lands on an empty page and
 * concludes their search matched nothing.
 */
import { STATUSES, statusLabel, type ProductFilters } from "@/lib/products";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none";

export function ProductFilterForm({ filters }: { filters: ProductFilters }) {
  return (
    <form
      method="get"
      className="mb-4 grid gap-3 rounded-[var(--radius-card)] border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4"
    >
      <label className="block text-xs text-muted lg:col-span-2">
        Search
        <input
          type="search"
          name="search"
          defaultValue={filters.search ?? ""}
          // Naming SKU in the placeholder because the backend searches `variants__sku`
          // and nothing on screen would otherwise suggest it. Staff read a SKU off the
          // jar far more often than they type a product's full name.
          placeholder="name or SKU…"
          className={`mt-1 ${FIELD}`}
        />
      </label>

      <label className="block text-xs text-muted">
        Status
        <select name="status" defaultValue={filters.status ?? ""} className={`mt-1 ${FIELD}`}>
          <option value="">Any</option>
          {STATUSES.map((status) => (
            <option key={status} value={status}>
              {statusLabel(status)}
            </option>
          ))}
        </select>
      </label>

      <div className="flex items-end gap-2">
        <button
          type="submit"
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
        >
          Search
        </button>
        {/* A link, not `type="reset"`: reset restores the fields to the values the page
            was rendered with, which on a filtered page is the filter itself. */}
        <a href="/products" className="text-sm text-muted underline-offset-2 hover:underline">
          Clear
        </a>
      </div>
    </form>
  );
}
