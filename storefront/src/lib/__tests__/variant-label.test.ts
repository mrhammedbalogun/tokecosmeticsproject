import { describe, it, expect } from "vitest";
import { variantLabel, variantLegend } from "@/lib/variant-label";
import type { Variant } from "@/lib/catalog";

const variant = (over: Partial<Variant> = {}): Variant => ({
  id: 1,
  sku: "TC-1",
  name: "Toke coco shea butter",
  option_values: {},
  price: null,
  in_stock: true,
  low_stock: false,
  ...over,
});

describe("variantLabel", () => {
  it("names a variant by its option values", () => {
    const v = variant({ option_values: { "Product Size": "175g" } });

    expect(variantLabel(v)).toBe("175g");
  });

  it("JOINS BOTH AXES, which is the whole bug", () => {
    // Production, live, before this fix: seven buttons all reading "Toke coco shea
    // butter" at ₦500 to ₦16,800, with nothing to tell them apart.
    const v = variant({
      option_values: { "Product Size": "175g", "Price Options": "Pack Price" },
    });

    expect(variantLabel(v)).toBe("175g · Pack Price");
  });

  it("distinguishes the seven variants that used to be identical", () => {
    const rows: [Record<string, string>, string][] = [
      [{ "Product Size": "35g (sample)", "Price Options": "Pieces" }, "35g (sample) · Pieces"],
      [{ "Product Size": "80g", "Price Options": "Pack Price" }, "80g · Pack Price"],
      [{ "Product Size": "80g", "Price Options": "Pieces" }, "80g · Pieces"],
      [{ "Product Size": "275g", "Price Options": "Pack Price" }, "275g · Pack Price"],
    ];
    const labels = rows.map(([options]) => variantLabel(variant({ option_values: options })));

    expect(labels).toEqual(rows.map(([, expected]) => expected));
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("falls back to the variant name when there is no option data", () => {
    // 52 production variants have none — every single-variant product. Those never render
    // a picker at all, but the fallback keeps the function honest on its own.
    expect(variantLabel(variant({ name: "Kids Shampoo" }))).toBe("Kids Shampoo");
  });

  it("falls back rather than rendering an empty pill for blank values", () => {
    expect(variantLabel(variant({ option_values: { Size: "   " } }))).toBe(
      "Toke coco shea butter",
    );
  });

  it("skips a blank axis but keeps the others", () => {
    const v = variant({ option_values: { "Product Size": "175g", "Price Options": "" } });

    expect(variantLabel(v)).toBe("175g");
  });

  it("survives option_values being absent entirely", () => {
    const v = { ...variant(), option_values: undefined } as unknown as Variant;

    expect(variantLabel(v)).toBe("Toke coco shea butter");
  });
});

describe("variantLegend", () => {
  it("names the axis from the data, not from a hardcoded 'Size'", () => {
    // `Product Size` on 55 production variants, `Size` on 12 — the same axis under two
    // WooCommerce labels. Asserting either one in code would be wrong for the other.
    const vs = [variant({ option_values: { "Product Size": "175g" } })];

    expect(variantLegend(vs)).toBe("Product Size");
  });

  it("names both axes on a two-axis product", () => {
    const vs = [
      variant({ option_values: { "Product Size": "175g", "Price Options": "Pieces" } }),
    ];

    expect(variantLegend(vs)).toBe("Product Size / Price Options");
  });

  it("lists each axis once however many variants carry it", () => {
    const vs = [
      variant({ id: 1, option_values: { "Product Size": "175g" } }),
      variant({ id: 2, option_values: { "Product Size": "275g" } }),
    ];

    expect(variantLegend(vs)).toBe("Product Size");
  });

  it("collects an axis that only some variants carry", () => {
    const vs = [
      variant({ id: 1, option_values: { "Product Size": "175g" } }),
      variant({ id: 2, option_values: { "Shea Variant": "Unscented" } }),
    ];

    expect(variantLegend(vs)).toBe("Product Size / Shea Variant");
  });

  it("says Options when there is nothing to name", () => {
    expect(variantLegend([variant()])).toBe("Options");
  });
});
