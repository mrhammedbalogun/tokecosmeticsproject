import { describe, it, expect } from "vitest";
import { parsePlpParams, plpHref } from "@/components/plp/plpParams";

describe("parsePlpParams", () => {
  it("keeps known params, coerces page, drops junk", () => {
    expect(parsePlpParams({ brand: "toke-naturals", page: "3", evil: "x", ordering: "price_asc" }))
      .toEqual({ brand: "toke-naturals", page: 3, ordering: "price_asc" });
  });
  it("rejects a non-numeric or <1 page and unknown orderings", () => {
    expect(parsePlpParams({ page: "abc", ordering: "hack" })).toEqual({ page: 1 });
  });
  it("array params (?brand=a&brand=b) take the first value", () => {
    expect(parsePlpParams({ brand: ["a", "b"] })).toEqual({ brand: "a", page: 1 });
  });
});

describe("plpHref", () => {
  it("builds an URL keeping current filters and swapping one key", () => {
    expect(plpHref("/products", { brand: "x", page: 3 }, { page: 4 }))
      .toBe("/products?brand=x&page=4");
    expect(plpHref("/products", { brand: "x", page: 3 }, { ordering: "price_desc" }))
      .toBe("/products?brand=x&ordering=price_desc");  // changing a filter resets page
  });
});
