import { describe, it, expect } from "vitest";
import { parseStoreFilters, storesQueryString } from "@/lib/stores";

/** Every bug this file guards against presents the same way on screen — "the filter
 *  silently did nothing" — which is why the trip from `searchParams` to the API query
 *  is tested without a request in sight. */
const parse = (qs: string) => parseStoreFilters(new URLSearchParams(qs));

describe("parseStoreFilters", () => {
  it("treats blank fields as absent — an untouched GET form must not filter", () => {
    // A GET form submits every field it holds, so `?q=&status=&country=` is what an
    // operator clicking Filter on an empty bar sends.
    expect(parse("q=&status=&country=&store_type=")).toEqual({ page: 1 });
  });

  it("keeps the filters it recognises and normalises the country code", () => {
    expect(parse("q=  beauty hub  &country=ng&store_type=distributor&status=inactive")).toEqual({
      page: 1,
      q: "beauty hub",
      country: "NG",
      store_type: "distributor",
      status: "inactive",
    });
  });

  it("drops an unrecognised status rather than forwarding a 400 to the operator", () => {
    // `?status=nonsense` reaches the API as no status at all, which shows the live
    // directory — harmless, and obviously what a hand-edited URL meant.
    expect(parse("status=nonsense")).toEqual({ page: 1 });
    expect(parse("store_type=franchise")).toEqual({ page: 1 });
  });

  it("keeps an area only when its state came with it", () => {
    expect(parse("state_region=17&area_region=302")).toEqual({
      page: 1,
      state_region: 17,
      area_region: 302,
    });
    // An orphan area id narrows the list in a way nothing on screen would explain.
    expect(parse("area_region=302")).toEqual({ page: 1 });
  });

  it("refuses a page that is not a positive whole number", () => {
    expect(parse("page=3").page).toBe(3);
    for (const bad of ["page=0", "page=-2", "page=1.5", "page=abc", "page="]) {
      expect(parse(bad).page).toBe(1);
    }
  });
});

describe("storesQueryString", () => {
  it("round-trips a full filter set", () => {
    const filters = parse("q=hub&country=NG&state_region=17&area_region=302&store_type=toke_store&status=active&page=2");
    expect(parse(storesQueryString(filters))).toEqual(filters);
  });

  it("omits page 1 — a bare list and `?page=1` are the same screen", () => {
    expect(storesQueryString({ page: 1 })).toBe("");
    expect(storesQueryString({ page: 2 })).toBe("page=2");
  });

  it("carries the active filters into a page link", () => {
    // Pagination builds every href through this; dropping a filter on page 2 would be
    // invisible, because page 2 of a filtered list and page 2 of the whole list look
    // identical.
    const filters = parse("country=NG&status=archived");
    expect(storesQueryString({ ...filters, page: 3 })).toBe("country=NG&status=archived&page=3");
  });
});
