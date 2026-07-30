import { describe, it, expect } from "vitest";
import {
  parseProductFilters,
  productsQueryString,
  statusLabel,
  unpricedIn,
  type ProductRow,
} from "@/lib/products";

const params = (qs: string) => new URLSearchParams(qs);

const row = (overrides: Partial<ProductRow> = {}): ProductRow => ({
  id: 1,
  name: "Carrot Shea Butter",
  slug: "carrot-shea-butter",
  status: "active",
  is_featured: false,
  updated_at: "2026-07-30T10:00:00Z",
  thumbnail: null,
  variant_count: 1,
  priced_currencies: [],
  ...overrides,
});

describe("parseProductFilters", () => {
  it("reads search and status", () => {
    expect(parseProductFilters(params("search=shea&status=draft"))).toEqual({
      search: "shea",
      status: "draft",
      page: 1,
    });
  });

  it("treats a blank field as absent", () => {
    // A GET form submits every field it contains, so an untouched form sends
    // `?search=&status=`. Forwarding those is two filters that each match everything.
    expect(parseProductFilters(params("search=&status="))).toEqual({ page: 1 });
  });

  it("trims surrounding whitespace", () => {
    expect(parseProductFilters(params("search=%20%20shea%20%20")).search).toBe("shea");
  });

  it("drops a whitespace-only search rather than sending it", () => {
    expect(parseProductFilters(params("search=%20%20")).search).toBeUndefined();
  });

  it("drops an unrecognised status instead of forwarding it", () => {
    // The backend answers 400 for `?status=nonsense`. An error page is the wrong response
    // to a hand-edited URL when "show everything" is harmless and obviously meant.
    expect(parseProductFilters(params("status=nonsense")).status).toBeUndefined();
  });

  it("defaults the page to 1 for anything that is not a positive integer", () => {
    for (const qs of ["", "page=", "page=0", "page=-2", "page=1.5", "page=abc", "page=%20"]) {
      expect(parseProductFilters(params(qs)).page).toBe(1);
    }
  });

  it("reads a real page number", () => {
    expect(parseProductFilters(params("page=7")).page).toBe(7);
  });
});

describe("productsQueryString", () => {
  it("omits page 1, so the unfiltered URL stays clean", () => {
    expect(productsQueryString({ page: 1 })).toBe("");
    expect(productsQueryString({ search: "shea", page: 1 })).toBe("search=shea");
  });

  it("writes the page from 2 onward", () => {
    expect(productsQueryString({ page: 2 })).toBe("page=2");
  });

  it("percent-encodes a search term", () => {
    // URLSearchParams and never string concatenation — a hand-built string would send a
    // raw `&` or `#` straight into the query it is part of.
    expect(productsQueryString({ search: "a&b #1", page: 1 })).toBe("search=a%26b+%231");
  });

  it("round-trips through parseProductFilters", () => {
    const filters = { search: "shea", status: "archived" as const, page: 3 };
    expect(parseProductFilters(params(productsQueryString(filters)))).toEqual(filters);
  });
});

describe("unpricedIn", () => {
  const configured = ["NGN", "GBP", "USD", "CAD"];

  it("names every currency the product has no price in", () => {
    // Production today: 121 prices, all NGN. Every product is invisible in three markets
    // and nothing in the admin says so. This column is why that stops being true.
    expect(unpricedIn(row({ priced_currencies: ["NGN"] }), configured)).toEqual([
      "GBP",
      "USD",
      "CAD",
    ]);
  });

  it("returns nothing when the product is priced everywhere", () => {
    expect(unpricedIn(row({ priced_currencies: configured }), configured)).toEqual([]);
  });

  it("names all of them when the product is priced nowhere", () => {
    expect(unpricedIn(row(), configured)).toEqual(configured);
  });

  it("preserves the configured order rather than sorting alphabetically", () => {
    // NGN first because it is the only market that can currently be sold to.
    expect(unpricedIn(row(), configured)[0]).toBe("NGN");
  });
});

describe("statusLabel", () => {
  it("capitalises the machine token", () => {
    expect(statusLabel("draft")).toBe("Draft");
    expect(statusLabel("active")).toBe("Active");
    expect(statusLabel("archived")).toBe("Archived");
  });
});
