import { describe, it, expect } from "vitest";
import {
  ordersQueryString,
  parseOrderFilters,
  reviewReasons,
  statusLabel,
} from "@/lib/orders";

const params = (qs: string) => new URLSearchParams(qs);

describe("parseOrderFilters", () => {
  it("reads the endpoint's whole vocabulary", () => {
    const filters = parseOrderFilters(
      params(
        "status=processing&country=NG&gateway=bank_transfer&search=TC-1" +
          "&placed_after=2026-01-01&placed_before=2026-12-31&needs_attention=true&page=3",
      ),
    );

    expect(filters).toEqual({
      status: "processing",
      country: "NG",
      gateway: "bank_transfer",
      search: "TC-1",
      placed_after: "2026-01-01",
      placed_before: "2026-12-31",
      needs_attention: true,
      page: 3,
    });
  });

  it("treats a blank field as absent", () => {
    // A GET form submits every field it contains; forwarding them is five filters that
    // each match everything.
    expect(parseOrderFilters(params("search=&country=&gateway="))).toEqual({ page: 1 });
  });

  it("drops an unrecognised status rather than forwarding it", () => {
    // Forwarded, the backend filters to nothing and an operator reads the empty table as
    // "no orders" rather than as a typo in the URL.
    expect(parseOrderFilters(params("status=nonsense")).status).toBeUndefined();
  });

  it("only honours needs_attention when it is the literal string the endpoint tests for", () => {
    expect(parseOrderFilters(params("needs_attention=true")).needs_attention).toBe(true);
    expect(parseOrderFilters(params("needs_attention=1")).needs_attention).toBeUndefined();
    expect(parseOrderFilters(params("needs_attention=yes")).needs_attention).toBeUndefined();
  });

  it("defaults the page for anything that is not a positive integer", () => {
    for (const qs of ["", "page=0", "page=-2", "page=1.5", "page=abc"]) {
      expect(parseOrderFilters(params(qs)).page).toBe(1);
    }
  });

  it("trims surrounding whitespace", () => {
    expect(parseOrderFilters(params("search=%20TC-1%20")).search).toBe("TC-1");
  });
});

describe("ordersQueryString", () => {
  it("omits page 1 so the unfiltered URL stays clean", () => {
    expect(ordersQueryString({ page: 1 })).toBe("");
  });

  it("writes needs_attention as the literal the endpoint tests for", () => {
    expect(ordersQueryString({ needs_attention: true, page: 1 })).toBe("needs_attention=true");
  });

  it("omits needs_attention entirely when false", () => {
    expect(ordersQueryString({ needs_attention: false, page: 1 })).toBe("");
  });

  it("percent-encodes a search term", () => {
    expect(ordersQueryString({ search: "a&b #1", page: 1 })).toBe("search=a%26b+%231");
  });

  it("round-trips through parseOrderFilters", () => {
    const filters = {
      status: "shipped" as const,
      country: "NG",
      gateway: "paystack",
      search: "jane@example.test",
      placed_after: "2026-01-01",
      placed_before: "2026-06-30",
      needs_attention: true,
      page: 4,
    };

    expect(parseOrderFilters(params(ordersQueryString(filters)))).toEqual(filters);
  });
});

describe("reviewReasons", () => {
  it("DOES NOT SPLIT ON THE SEPARATOR, because one reason contains it", () => {
    // payments/services.py writes:
    //   "possible double payment — order already processing; refund payment 7"
    // and _add_review_reason joins with "; ". Splitting turns that one sentence into two
    // fragments, the second reading as an instruction with no context. Nothing here can
    // recover the intent, so the text is rendered verbatim.
    const order = {
      review_reason:
        "overpaid by 500.00 NGN — refund the difference; " +
        "possible double payment — order already processing; refund payment 7",
    };

    expect(reviewReasons(order)).toEqual([order.review_reason]);
  });

  it("is empty for an unflagged order", () => {
    expect(reviewReasons({ review_reason: "" })).toEqual([]);
    expect(reviewReasons({ review_reason: "   " })).toEqual([]);
  });

  it("returns a single reason unchanged", () => {
    const one = "payment 3 received on a cancelled order — refund it";

    expect(reviewReasons({ review_reason: one })).toEqual([one]);
  });

  it("does not interpret the text", () => {
    // Human sentences with amounts baked in. Anything that pattern-matched them would
    // break the first time one is reworded.
    const odd = "something nobody has written yet — with an em dash and 1,234.56";

    expect(reviewReasons({ review_reason: odd })).toEqual([odd]);
  });
});

describe("statusLabel", () => {
  it("turns the machine token into a sentence", () => {
    expect(statusLabel("pending_payment")).toBe("Pending payment");
    expect(statusLabel("on_hold")).toBe("On hold");
    expect(statusLabel("shipped")).toBe("Shipped");
  });
});
