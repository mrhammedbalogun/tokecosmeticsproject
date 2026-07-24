import { describe, it, expect } from "vitest";
import { initialVariant } from "@/components/product/PdpContext";
import type { Variant } from "@/lib/catalog";

const v = (id: number, in_stock: boolean, price = true): Variant => ({
  id, sku: `S${id}`, name: `${id}0ml`, option_values: { Size: `${id}0ml` },
  in_stock, low_stock: false,
  price: price ? { amount: "1000.00", compare_at: null, currency: "NGN",
                   tax_rate: "0.00", prices_include_tax: true } : null,
});

describe("initialVariant", () => {
  it("prefers the first in-stock, priced variant", () => {
    expect(initialVariant([v(1, false), v(2, true)])?.id).toBe(2);
  });
  it("falls back to the first priced variant when all are out of stock", () => {
    expect(initialVariant([v(1, false), v(2, false)])?.id).toBe(1);
  });
  it("ignores unpriced variants; null when none priced", () => {
    expect(initialVariant([v(1, true, false)])).toBeNull();
  });
});
