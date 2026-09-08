import { describe, it, expect } from "vitest";
import { initialVariant, optionSelections, purchasable } from "@/components/product/PdpContext";
import type { Variant } from "@/lib/catalog";

const v = (id: number, in_stock: boolean, price = true): Variant => ({
  id, sku: `S${id}`, name: `${id}0ml`, option_values: { Size: `${id}0ml` },
  in_stock, low_stock: false,
  price: price ? { amount: "1000.00", compare_at: null, currency: "NGN",
                   tax_rate: "0.00", prices_include_tax: true } : null,
});

describe("initialVariant", () => {
  it("pre-selects the lone purchasable variant — there is nothing to choose", () => {
    expect(initialVariant([v(1, true)])?.id).toBe(1);
  });
  it("pre-selects it even when it is out of stock", () => {
    expect(initialVariant([v(1, false)])?.id).toBe(1);
  });
  it("pre-selects nothing when the shopper has a real choice", () => {
    // The whole point: this used to return the first in-stock priced variant, and
    // shoppers bought it believing it was the only size on offer.
    expect(initialVariant([v(1, true), v(2, true)])).toBeNull();
    expect(initialVariant([v(1, false), v(2, false)])).toBeNull();
  });
  it("counts only priced variants, so one price among many is still no choice", () => {
    expect(initialVariant([v(1, true, false), v(2, true)])?.id).toBe(2);
  });
  it("is null when nothing is priced here", () => {
    expect(initialVariant([v(1, true, false), v(2, true, false)])).toBeNull();
  });
});

describe("purchasable", () => {
  it("keeps priced variants, in stock or not", () => {
    expect(purchasable([v(1, false), v(2, true, false), v(3, true)]).map((x) => x.id))
      .toEqual([1, 3]);
  });
});

describe("optionSelections", () => {
  it("reads the axis answers a variant stands for, dropping blanks", () => {
    const variant = { ...v(1, true), option_values: { Size: " 50ml ", Colour: "  " } };
    expect(optionSelections(variant)).toEqual({ Size: "50ml" });
  });
});
