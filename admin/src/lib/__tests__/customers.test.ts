import { describe, expect, it } from "vitest";
import {
  customersQueryString,
  formatTotal,
  parseCustomerFilters,
  sourceLabel,
} from "@/lib/customers";

describe("parseCustomerFilters", () => {
  it("defaults to page 1 and no filters", () => {
    expect(parseCustomerFilters(new URLSearchParams())).toEqual({
      search: "", legacy_source: "", is_active: "", page: 1,
    });
  });

  it("REJECTS A NON-INTEGER PAGE rather than putting it in a query string", () => {
    // isSafeInteger, not isInteger: 1e21 IS an integer to isInteger and would reach the
    // API in exponent form.
    for (const bad of ["0", "-3", "abc", "1e21", ""]) {
      expect(parseCustomerFilters(new URLSearchParams({ page: bad })).page).toBe(1);
    }
  });

  it("trims the search term", () => {
    expect(parseCustomerFilters(new URLSearchParams({ search: "  ada  " })).search).toBe("ada");
  });
});

describe("customersQueryString", () => {
  it("omits page 1 so the canonical list URL is clean", () => {
    const filters = parseCustomerFilters(new URLSearchParams({ search: "ada" }));
    expect(customersQueryString(filters)).toBe("search=ada");
  });

  it("KEEPS THE FILTERS ON EVERY PAGE LINK", () => {
    // Page 2 of a filtered list and page 2 of the whole list look identical, so dropping
    // the filter would be invisible.
    const filters = parseCustomerFilters(
      new URLSearchParams({ search: "ada", legacy_source: "legacy_ng" }),
    );
    const qs = customersQueryString(filters, 3);
    expect(qs).toContain("search=ada");
    expect(qs).toContain("legacy_source=legacy_ng");
    expect(qs).toContain("page=3");
  });
});

describe("sourceLabel", () => {
  it("names the store a migrated customer came from", () => {
    expect(sourceLabel("legacy_ng_old")).toBe("Nigeria (old store)");
  });

  it("says where an organic signup came from rather than showing a blank", () => {
    expect(sourceLabel("")).toBe("Signed up here");
  });

  it("shows an unrecognised source verbatim rather than dropping it", () => {
    expect(sourceLabel("legacy_future")).toBe("legacy_future");
  });
});

describe("formatTotal", () => {
  it("KEEPS THE CURRENCY ATTACHED TO ITS AMOUNT", () => {
    // The project bans FX mixing and Plan-23 imports four currencies of history, so an
    // amount without its currency is not a number anybody can act on.
    expect(formatTotal({ currency: "NGN", orders: 2, lifetime_value: "15000.00" }))
      .toBe("NGN 15,000");
  });

  it("passes a malformed amount through rather than rendering NaN", () => {
    expect(formatTotal({ currency: "GBP", orders: 1, lifetime_value: "oops" }))
      .toBe("GBP oops");
  });
});
