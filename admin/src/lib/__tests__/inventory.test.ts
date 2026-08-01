import { describe, it, expect } from "vitest";
import {
  cellState,
  inventoryQueryString,
  parseInventoryFilters,
  rowTotal,
  type GridCell,
  type GridRow,
} from "@/lib/inventory";

const cell = (over: Partial<GridCell> = {}): GridCell => ({
  warehouse_id: 1,
  warehouse_name: "Lagos HQ",
  stock_item_id: 10,
  quantity: 40,
  reserved: 0,
  available: 40,
  low_stock_threshold: 5,
  is_low: false,
  ...over,
});

const row = (cells: GridCell[]): GridRow => ({
  variant_id: 1,
  sku: "SKU-1",
  variant_name: "30ml",
  product_name: "Serum",
  product_slug: "serum",
  cells,
});

describe("cellState", () => {
  it("calls a cell with no stock row ABSENT, not zero", () => {
    // The distinction the whole screen rests on: 0 means somebody counted and found
    // none; absent means nobody has ever counted here.
    expect(cellState(cell({ stock_item_id: null, quantity: null }))).toBe("absent");
  });

  it("calls a real zero a count, not an absence", () => {
    expect(cellState(cell({ quantity: 0, is_low: true }))).toBe("low");
  });

  it("reports low against the row's own threshold, as the API decided", () => {
    expect(cellState(cell({ quantity: 3, is_low: true }))).toBe("low");
    expect(cellState(cell({ quantity: 90, is_low: false }))).toBe("counted");
  });
});

describe("rowTotal", () => {
  it("adds the counted cells", () => {
    expect(rowTotal(row([cell({ quantity: 40 }), cell({ warehouse_id: 2, quantity: 2 })]))).toBe(42);
  });

  it("IGNORES uncounted cells rather than treating them as zero", () => {
    expect(
      rowTotal(row([cell({ quantity: 40 }), cell({ warehouse_id: 2, stock_item_id: null, quantity: null })])),
    ).toBe(40);
  });

  it("returns null when nothing has been counted anywhere", () => {
    // Printing 0 would assert a count that never happened.
    expect(rowTotal(row([cell({ stock_item_id: null, quantity: null })]))).toBeNull();
  });
});

describe("the query vocabulary", () => {
  it("round-trips the filters the endpoint actually reads", () => {
    const filters = parseInventoryFilters(
      new URLSearchParams("search=shea&low_stock=1&warehouse=2&page=3"),
    );

    expect(filters).toEqual({ search: "shea", lowStock: true, warehouse: "2", page: 3 });
    expect(inventoryQueryString(filters)).toBe("search=shea&low_stock=1&warehouse=2&page=3");
  });

  it("omits empty keys, so links do not carry noise", () => {
    expect(inventoryQueryString({ search: "", lowStock: false, warehouse: "", page: 1 })).toBe("");
  });

  it("falls back to page 1 on a nonsense page number", () => {
    expect(parseInventoryFilters(new URLSearchParams("page=nope")).page).toBe(1);
    expect(parseInventoryFilters(new URLSearchParams("page=-4")).page).toBe(1);
  });
});
