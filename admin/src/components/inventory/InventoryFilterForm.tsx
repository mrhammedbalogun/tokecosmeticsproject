/**
 * The inventory filters. A plain GET form, so the filter state lives in the URL and a
 * filtered grid can be linked, bookmarked and reloaded — the same choice the products and
 * orders lists made.
 *
 * `page` is deliberately absent: changing a filter must return to page 1, and carrying the
 * old page number would land somebody on an empty page of a shorter result set.
 */
import type { InventoryFilters, WarehouseColumn } from "@/lib/inventory";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export function InventoryFilterForm({
  filters,
  warehouses,
}: {
  filters: InventoryFilters;
  warehouses: WarehouseColumn[];
}) {
  return (
    <form
      method="get"
      className="grid gap-3 rounded-[var(--radius-card)] border border-line p-4 sm:grid-cols-[1fr_12rem_auto_auto]"
    >
      <label className="block text-xs text-muted">
        Search
        <input
          type="text"
          name="search"
          defaultValue={filters.search}
          placeholder="SKU or product name…"
          className={`mt-1 ${FIELD}`}
        />
      </label>

      <label className="block text-xs text-muted">
        Warehouse
        <select name="warehouse" defaultValue={filters.warehouse} className={`mt-1 ${FIELD}`}>
          <option value="">All warehouses</option>
          {warehouses.map((warehouse) => (
            <option key={warehouse.id} value={warehouse.id}>
              {warehouse.name}
            </option>
          ))}
        </select>
      </label>

      <label className="flex items-end gap-2 text-sm">
        <input
          type="checkbox"
          name="low_stock"
          value="1"
          defaultChecked={filters.lowStock}
          className="mb-2 h-4 w-4 rounded border-line"
        />
        <span className="mb-1.5">Low stock only</span>
      </label>

      <div className="flex items-end gap-2">
        <button
          type="submit"
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
        >
          Apply
        </button>
        <a href="/inventory" className="py-1.5 text-sm text-muted hover:text-foreground">
          Clear
        </a>
      </div>
    </form>
  );
}
