import { describe, it, expect } from "vitest";
import { parseSearchParams, first } from "@/lib/search-params";

describe("first", () => {
  it("collapses a repeated param to its first value", () => {
    expect(first(["a", "b"])).toBe("a");
    expect(first("a")).toBe("a");
    expect(first(undefined)).toBe(undefined);
  });
});

describe("parseSearchParams", () => {
  it("trims and keeps a real query", () => {
    expect(parseSearchParams({ q: "  glow  " })).toEqual({ q: "glow" });
  });

  it("drops an empty/whitespace query", () => {
    expect(parseSearchParams({ q: "   " })).toEqual({});
    expect(parseSearchParams({})).toEqual({});
  });

  it("coerces page like parsePlpParams — integers > 1 only", () => {
    expect(parseSearchParams({ q: "x", page: "3" }).page).toBe(3);
    expect(parseSearchParams({ q: "x", page: "1" }).page).toBeUndefined();  // default
    expect(parseSearchParams({ q: "x", page: "1.5" }).page).toBeUndefined(); // non-integer
    expect(parseSearchParams({ q: "x", page: "-4" }).page).toBeUndefined();  // negative
    expect(parseSearchParams({ q: "x", page: "abc" }).page).toBeUndefined(); // NaN
    expect(parseSearchParams({ q: "x", page: "0" }).page).toBeUndefined();
  });

  it("whitelists sort against the real backend options", () => {
    expect(parseSearchParams({ q: "x", sort: "price_asc" }).sort).toBe("price_asc");
    expect(parseSearchParams({ q: "x", sort: "price_desc" }).sort).toBe("price_desc");
    expect(parseSearchParams({ q: "x", sort: "newest" }).sort).toBe("newest");
    expect(parseSearchParams({ q: "x", sort: "ordering" }).sort).toBeUndefined(); // PLP param, rejected
    expect(parseSearchParams({ q: "x", sort: "evil" }).sort).toBeUndefined();
    expect(parseSearchParams({ q: "x", sort: "" }).sort).toBeUndefined();
  });

  it("treats in_stock as a strict opt-in (only '1')", () => {
    expect(parseSearchParams({ q: "x", in_stock: "1" }).in_stock).toBe("1");
    expect(parseSearchParams({ q: "x", in_stock: "true" }).in_stock).toBeUndefined();
    expect(parseSearchParams({ q: "x", in_stock: "0" }).in_stock).toBeUndefined();
    expect(parseSearchParams({ q: "x", in_stock: "" }).in_stock).toBeUndefined();
  });

  it("collapses repeated params before parsing", () => {
    expect(parseSearchParams({ q: ["glow", "serum"], sort: ["newest", "evil"] }))
      .toEqual({ q: "glow", sort: "newest" });
  });

  it("builds a full param set", () => {
    expect(parseSearchParams({ q: "serum", page: "2", sort: "price_asc", in_stock: "1" }))
      .toEqual({ q: "serum", page: 2, sort: "price_asc", in_stock: "1" });
  });
});
