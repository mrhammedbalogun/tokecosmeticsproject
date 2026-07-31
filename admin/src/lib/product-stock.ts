/**
 * Stock rows as the Variants tab reads them, plus the warehouse columns derived from them.
 *
 * THE WAREHOUSE LIST COMES FROM THE STOCK ROWS, not from a warehouse endpoint — there is
 * none until 17c, which is where Warehouse CRUD lives. `StockItemSerializer` carries
 * `warehouse_name`, and that is the whole source of the column heading.
 *
 * The consequence is worth stating rather than discovering: a warehouse holding NO stock
 * for this product contributes no column. Production has two warehouses and one stock row
 * per variant, so a product will routinely show one column and not two. That is honest —
 * the tab reports what stock exists, not what warehouses could exist — but it means the
 * columns differ between products, and 17c's warehouse endpoint is what makes them stable.
 */

export interface StockRow {
  id: number;
  variant: number;
  sku: string;
  warehouse: number;
  warehouse_name: string;
  quantity: number;
  reserved: number;
  available: number;
  low_stock_threshold: number;
}

export interface WarehouseColumn {
  id: number;
  name: string;
}

/** The warehouses present in these stock rows, deduplicated and ordered by name so the
 *  columns do not reshuffle between renders of the same data. */
export function warehouseColumns(stock: StockRow[]): WarehouseColumn[] {
  const seen = new Map<number, string>();
  for (const row of stock) {
    if (!seen.has(row.warehouse)) seen.set(row.warehouse, row.warehouse_name);
  }
  return [...seen.entries()]
    .map(([id, name]) => ({ id, name }))
    .sort((a, b) => a.name.localeCompare(b.name) || a.id - b.id);
}

/** Total on-hand across every warehouse, for a variant. */
export function totalQuantity(stock: StockRow[], variantId: number): number {
  return stock
    .filter((row) => row.variant === variantId)
    .reduce((total, row) => total + row.quantity, 0);
}
