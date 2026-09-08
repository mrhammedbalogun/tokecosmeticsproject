import { describe, it, expect } from "vitest";
import { matchVariant, variantAxes, variantsMatching } from "@/lib/variant-axes";
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

describe("variantsMatching", () => {
  it("narrows to the variants agreeing with a partial selection", () => {
    expect(variantsMatching(grid, { Size: "1l" }).map((v) => v.option_values.Colour))
      .toEqual(["red", "blue"]);
  });
  it("returns every variant for an empty selection, none for an unknown value", () => {
    expect(variantsMatching(grid, {})).toHaveLength(4);
    expect(variantsMatching(grid, { Size: "9l" })).toEqual([]);
  });
});
