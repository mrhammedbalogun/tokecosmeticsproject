import { describe, it, expect } from "vitest";
import { totalQuantity, warehouseColumns, type StockRow } from "@/lib/product-stock";

const row = (overrides: Partial<StockRow> & { variant: number; warehouse: number }): StockRow => ({
  id: 1,
  sku: "SKU-1",
  warehouse_name: "Lagos HQ",
  quantity: 10,
  reserved: 0,
  available: 10,
  low_stock_threshold: 5,
  ...overrides,
});

describe("warehouseColumns", () => {
  it("derives the columns from the stock rows, since no warehouse endpoint exists yet", () => {
    // Warehouse CRUD is 17c. `StockItemSerializer.warehouse_name` is the whole source of
    // the column heading until then.
    const columns = warehouseColumns([
      row({ variant: 1, warehouse: 2, warehouse_name: "UK Warehouse" }),
      row({ variant: 2, warehouse: 1, warehouse_name: "Lagos HQ" }),
    ]);

    expect(columns).toEqual([
      { id: 1, name: "Lagos HQ" },
      { id: 2, name: "UK Warehouse" },
    ]);
  });

  it("lists each warehouse once however many variants stock it", () => {
    const columns = warehouseColumns([
      row({ variant: 1, warehouse: 1 }),
      row({ variant: 2, warehouse: 1 }),
      row({ variant: 3, warehouse: 1 }),
    ]);

    expect(columns).toHaveLength(1);
  });

  it("orders by name so the columns do not reshuffle between renders", () => {
    const columns = warehouseColumns([
      row({ variant: 1, warehouse: 9, warehouse_name: "Zaria" }),
      row({ variant: 2, warehouse: 3, warehouse_name: "Abuja" }),
    ]);

    expect(columns.map((c) => c.name)).toEqual(["Abuja", "Zaria"]);
  });

  it("is empty when the product has no stock anywhere", () => {
    // Not an error state: production keeps one stock row per variant across two
    // warehouses, so a product legitimately shows fewer columns than there are warehouses.
    expect(warehouseColumns([])).toEqual([]);
  });
});

describe("totalQuantity", () => {
  it("sums across warehouses for one variant", () => {
    const stock = [
      row({ variant: 1, warehouse: 1, quantity: 4 }),
      row({ variant: 1, warehouse: 2, quantity: 6 }),
      row({ variant: 2, warehouse: 1, quantity: 99 }),
    ];

    expect(totalQuantity(stock, 1)).toBe(10);
  });

  it("is zero for a variant with no stock rows", () => {
    expect(totalQuantity([], 1)).toBe(0);
  });
});
