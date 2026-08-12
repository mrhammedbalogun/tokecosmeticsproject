import { describe, it, expect } from "vitest";
import { matchVariant, pickVariant, variantAxes } from "@/lib/variant-axes";
import type { Variant } from "@/lib/catalog";

let nextId = 1;
const v = (
  option_values: Record<string, string>,
  { in_stock = true, priced = true } = {},
): Variant => ({
  id: nextId++, sku: `S${nextId}`, name: "test product", option_values,
  in_stock, low_stock: false,
  price: priced
    ? { amount: "1000.00", compare_at: null, currency: "NGN",
        tax_rate: "0.00", prices_include_tax: true }
    : null,
});

const grid = [
  v({ Size: "1l", Colour: "red" }),
  v({ Size: "1l", Colour: "blue" }),
  v({ Size: "2l", Colour: "red" }, { in_stock: false }),
  v({ Size: "2l", Colour: "blue" }, { priced: false }),
];

describe("variantAxes", () => {
  it("collects distinct axes with values in first-appearance order", () => {
    expect(variantAxes(grid)).toEqual([
      { name: "Size", values: ["1l", "2l"] },
      { name: "Colour", values: ["red", "blue"] },
    ]);
  });
  it("ignores blank values and handles variants without option data", () => {
    expect(variantAxes([v({ Size: " " }), v({})])).toEqual([]);
  });
});

describe("matchVariant", () => {
  it("finds the exact combination", () => {
    expect(matchVariant(grid, { Size: "2l", Colour: "red" })?.id).toBe(grid[2].id);
  });
  it("returns null for a combination the product does not offer", () => {
    expect(matchVariant(grid, { Size: "3l", Colour: "red" })).toBeNull();
  });
});

describe("pickVariant", () => {
  it("holds the other axes when the exact combination exists", () => {
    const picked = pickVariant(grid, { Size: "1l", Colour: "blue" }, "Size", "2l");
    expect(picked?.id).toBe(grid[3].id);
  });
  it("falls back to an in-stock priced variant when the combination is missing", () => {
    // 3l only exists in orange; choosing it must land somewhere sellable.
    const sparse = [...grid, v({ Size: "3l", Colour: "orange" })];
    const picked = pickVariant(sparse, { Size: "1l", Colour: "red" }, "Size", "3l");
    expect(picked?.option_values).toEqual({ Size: "3l", Colour: "orange" });
  });
  it("prefers priced over unpriced in the fallback", () => {
    const sparse = [
      v({ Size: "5l", Colour: "red" }, { priced: false }),
      v({ Size: "5l", Colour: "blue" }, { in_stock: false }),
    ];
    const picked = pickVariant(sparse, { Colour: "green" }, "Size", "5l");
    expect(picked?.option_values.Colour).toBe("blue");
  });
  it("returns null when no variant carries the value", () => {
    expect(pickVariant(grid, {}, "Size", "9l")).toBeNull();
  });
});
