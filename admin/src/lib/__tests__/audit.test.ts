import { describe, it, expect } from "vitest";
import {
  PAGE_SIZE,
  auditQueryString,
  describeChanges,
  parseAuditFilters,
  pageCount,
  pageWindow,
} from "@/lib/audit";

describe("parseAuditFilters", () => {
  it("keeps only the filters the backend understands", () => {
    // A page whose URL carries junk should not forward it. The backend's audit list
    // reads five named parameters and ignores the rest, so forwarding an unknown one is
    // silently ineffective — which reads to an operator as "the filter is broken".
    const filters = parseAuditFilters(
      new URLSearchParams({ actor: "owner@toke.test", nonsense: "x", page: "3" }),
    );

    expect(filters).toEqual({ actor: "owner@toke.test", page: 3 });
  });

  it("drops blank values rather than sending empty filters", () => {
    // An HTML form submits every field, including the ones left empty. `?actor=` is not
    // "no filter" to the backend — it is `actor_email__icontains=""`, which matches
    // everything but still costs the ILIKE.
    const filters = parseAuditFilters(new URLSearchParams({ actor: "", model: "  ", action: "create" }));

    expect(filters).toEqual({ action: "create", page: 1 });
  });

  it("defaults to page 1 when the page parameter is not a positive integer", () => {
    for (const page of ["0", "-2", "abc", "1.5", ""]) {
      expect(parseAuditFilters(new URLSearchParams({ page })).page).toBe(1);
    }
  });
});

describe("auditQueryString", () => {
  it("round-trips the filters back onto the API call", () => {
    const qs = auditQueryString({ actor: "owner@toke.test", model: "catalog.product", page: 2 });

    expect(qs).toBe("actor=owner%40toke.test&model=catalog.product&page=2");
  });

  it("percent-encodes a '+' offset in a timestamp", () => {
    // THE GOTCHA THE BACKEND WROTE A 400 MESSAGE ABOUT. A '+' in a query string is a
    // SPACE, so an un-encoded ISO offset arrives as `2026-07-30T06:33:52 00:00` and the
    // endpoint answers 400. URLSearchParams encodes it; this test is here so nobody
    // "simplifies" it into string concatenation.
    const qs = auditQueryString({ after: "2026-07-30T06:33:52+00:00", page: 1 });

    expect(qs).toContain("after=2026-07-30T06%3A33%3A52%2B00%3A00");
    expect(qs).not.toContain("+00:00");
  });

  it("omits page 1, so the first page has a clean URL", () => {
    expect(auditQueryString({ actor: "x", page: 1 })).toBe("actor=x");
  });
});

describe("pageCount", () => {
  it("is the number of pages the backend's count implies", () => {
    expect(pageCount(0)).toBe(1); // an empty log is still one (empty) page
    expect(pageCount(1)).toBe(1);
    expect(pageCount(PAGE_SIZE)).toBe(1);
    expect(pageCount(PAGE_SIZE + 1)).toBe(2);
  });
});

describe("pageWindow", () => {
  it("shows every page when there are few", () => {
    expect(pageWindow(2, 4)).toEqual([1, 2, 3, 4]);
  });

  it("centres on the current page in a long log and marks the gaps", () => {
    expect(pageWindow(20, 50)).toEqual([1, "…", 19, 20, 21, "…", 50]);
  });

  it("never renders a gap marker standing in for a single page", () => {
    // `1 … 3` is longer than `1 2 3` and one click worse. The window must collapse the
    // marker when it would hide exactly one number.
    expect(pageWindow(3, 5)).toEqual([1, 2, 3, 4, 5]);
  });
});

describe("describeChanges", () => {
  it("summarises a changes object as field names, not values", () => {
    // The row's `changes` can hold a customer's address. The TABLE shows which fields
    // moved; the values stay behind the expander. A table that renders them puts PII on
    // screen for every row at once, which is exactly the shape of an accidental leak
    // over somebody's shoulder.
    expect(describeChanges({ price: ["100", "120"], status: ["draft", "active"] })).toBe(
      "price, status",
    );
  });

  it("says so plainly when a row recorded nothing", () => {
    expect(describeChanges({})).toBe("—");
    expect(describeChanges(null)).toBe("—");
  });

  it("names the query parameters for a read-audited row", () => {
    expect(describeChanges({ query_params: { q: "ada" } })).toBe("query_params");
  });
});
