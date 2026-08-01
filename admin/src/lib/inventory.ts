/**
 * Shapes and query handling for the inventory grid. No fetching — that is
 * `app/(shell)/inventory/page.tsx`.
 *
 * THE FILTER VOCABULARY IS THE ENDPOINT'S. `StockItemAdminViewSet.grid` reads `search`,
 * `low_stock`, `warehouse` and `page` and ignores anything else, so offering a control
 * this list does not name would give an operator a switch that silently does nothing.
 */
import { PAGE_SIZE } from "@/lib/pagination";

export { PAGE_SIZE };

/**
 * One variant × warehouse cell.
 *
 * `stock_item_id: null` is the case this screen exists for. Production holds 122 stock
 * rows against 244 possible cells, and every empty one is the UK Warehouse — an absence
 * that was invisible on every other screen. It is NOT a zero: zero means somebody counted
 * and found none, null means nobody has ever counted here.
 */
export interface GridCell {
  warehouse_id: number;
  warehouse_name: string;
  stock_item_id: number | null;
  quantity: number | null;
  reserved: number | null;
  available: number | null;
  low_stock_threshold: number | null;
  is_low: boolean;
}

export interface GridRow {
  variant_id: number;
  sku: string;
  variant_name: string;
  product_name: string;
  product_slug: string;
  cells: GridCell[];
}

export interface WarehouseColumn {
  id: number;
  name: string;
}

export interface GridPage {
  count: number;
  results: GridRow[];
  warehouses: WarehouseColumn[];
}

export interface InventoryFilters {
  search: string;
  lowStock: boolean;
  warehouse: string;
  page: number;
}

export function parseInventoryFilters(params: URLSearchParams): InventoryFilters {
  const page = Number(params.get("page") ?? "1");
  return {
    search: (params.get("search") ?? "").trim(),
    lowStock: params.get("low_stock") === "1",
    warehouse: (params.get("warehouse") ?? "").trim(),
    page: Number.isFinite(page) && page >= 1 ? Math.floor(page) : 1,
  };
}

/** Only keys the endpoint reads, and only when they carry a value — an empty `search=`
 *  in the URL is noise in every link the page builds from it. */
export function inventoryQueryString(filters: InventoryFilters): string {
  const qs = new URLSearchParams();
  if (filters.search) qs.set("search", filters.search);
  if (filters.lowStock) qs.set("low_stock", "1");
  if (filters.warehouse) qs.set("warehouse", filters.warehouse);
  if (filters.page > 1) qs.set("page", String(filters.page));
  return qs.toString();
}

/**
 * What a cell shows. Split out from the component so the three states have one
 * definition and can be tested without rendering anything.
 *
 * The three are genuinely different and the screen must not blur them:
 *   absent  — no row anywhere; the fix is to create one
 *   low     — a real count at or below its own threshold; the fix is to restock
 *   counted — an ordinary number
 */
export type CellState = "absent" | "low" | "counted";

export function cellState(cell: GridCell): CellState {
  if (cell.stock_item_id === null) return "absent";
  return cell.is_low ? "low" : "counted";
}

/** Total on-hand for a row, ignoring cells nobody has counted. Returns null when there is
 *  nothing counted anywhere — printing `0` there would assert a count that never happened. */
export function rowTotal(row: GridRow): number | null {
  const counted = row.cells.filter((c) => c.quantity !== null);
  if (!counted.length) return null;
  return counted.reduce((sum, c) => sum + (c.quantity ?? 0), 0);
}
