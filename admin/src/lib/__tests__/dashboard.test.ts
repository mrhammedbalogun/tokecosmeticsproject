import { describe, it, expect } from "vitest";
import {
  buildBars,
  deltaTone,
  formatDelta,
  orderStatuses,
  pairByCurrency,
  percentDelta,
  previousRange,
  type DayRow,
  type RevenueRow,
} from "@/lib/dashboard";

const row = (over: Partial<RevenueRow> = {}): RevenueRow => ({
  currency: "NGN", orders: 5, gross: "35100", refunds: "0", net: "35100", aov: "7020",
  ...over,
});

describe("percentDelta", () => {
  it("IS NULL WHEN THE PREVIOUS PERIOD WAS ZERO", () => {
    // The trap: dividing gives Infinity, and "+∞%" on a dashboard is how somebody
    // decides none of the numbers on the page can be trusted.
    expect(percentDelta(100, 0)).toBeNull();
    expect(formatDelta(percentDelta(100, 0))).toBe("—");
  });

  it("computes an ordinary change", () => {
    expect(percentDelta(150, 100)).toBeCloseTo(50);
    expect(percentDelta(50, 100)).toBeCloseTo(-50);
  });

  it("survives a non-finite input rather than rendering NaN", () => {
    expect(percentDelta(Number.NaN, 100)).toBeNull();
  });

  it("formats with a sign and one decimal", () => {
    expect(formatDelta(12.34)).toBe("+12.3%");
    expect(formatDelta(-8)).toBe("-8.0%");
    expect(formatDelta(0.01)).toBe("0.0%");
  });
});

describe("deltaTone", () => {
  it("READS REFUNDS THE OTHER WAY ROUND", () => {
    // More revenue is good news; more refunds is not. The caller says which, rather
    // than the formatter guessing from the sign.
    expect(deltaTone(20, true)).toBe("up");
    expect(deltaTone(20, false)).toBe("down");
  });

  it("is flat for null or negligible movement", () => {
    expect(deltaTone(null)).toBe("flat");
    expect(deltaTone(0.01)).toBe("flat");
  });
});

describe("pairByCurrency", () => {
  it("KEEPS A CURRENCY THAT APPEARS IN ONLY ONE PERIOD", () => {
    // A market that stopped selling is exactly what a delta is for; dropping it would
    // hide the thing worth noticing.
    const pairs = pairByCurrency([row({ currency: "NGN" })], [row({ currency: "GBP" })]);

    expect(pairs.map((p) => p.currency)).toEqual(["GBP", "NGN"]);
    expect(pairs.find((p) => p.currency === "GBP")?.current).toBeNull();
    expect(pairs.find((p) => p.currency === "NGN")?.previous).toBeNull();
  });
});

describe("buildBars", () => {
  const rows: DayRow[] = [
    { day: "2026-08-01T00:00:00Z", currency_id: "NGN", orders: 1, gross: "100" },
    { day: "2026-08-03T00:00:00Z", currency_id: "NGN", orders: 1, gross: "300" },
  ];

  it("FILLS QUIET DAYS, so time is not compressed", () => {
    const bars = buildBars(rows, "2026-08-01", "2026-08-03");

    expect(bars.map((b) => b.day)).toEqual(["2026-08-01", "2026-08-02", "2026-08-03"]);
    expect(bars.map((b) => b.value)).toEqual([100, 0, 300]);
  });

  it("scales heights against the tallest bar", () => {
    const bars = buildBars(rows, "2026-08-01", "2026-08-03");

    expect(bars[2].height).toBe(1);
    expect(bars[0].height).toBeCloseTo(1 / 3);
  });

  it("gives every bar zero height when nothing sold, rather than dividing by zero", () => {
    const bars = buildBars([], "2026-08-01", "2026-08-02");

    expect(bars).toHaveLength(2);
    expect(bars.every((b) => b.height === 0)).toBe(true);
  });

  it("does not loop forever on a reversed range", () => {
    expect(buildBars([], "2026-08-05", "2026-08-01")).toEqual([]);
  });
});

describe("orderStatuses", () => {
  it("orders statuses by lifecycle, not by count, so the strip does not reshuffle", () => {
    const ordered = orderStatuses([
      { status: "completed", orders: 9 },
      { status: "pending_payment", orders: 1 },
    ]);

    expect(ordered.map((r) => r.status)).toEqual(["pending_payment", "completed"]);
  });

  it("appends an unknown status rather than dropping it", () => {
    const ordered = orderStatuses([{ status: "invented", orders: 2 }]);

    expect(ordered.map((r) => r.status)).toEqual(["invented"]);
  });
});

describe("previousRange", () => {
  it("is the same LENGTH immediately before, so like compares with like", () => {
    expect(previousRange("2026-08-01", "2026-08-30")).toEqual({
      start: "2026-07-02",
      end: "2026-07-31",
    });
  });

  it("handles a single day", () => {
    expect(previousRange("2026-08-01", "2026-08-01")).toEqual({
      start: "2026-07-31",
      end: "2026-07-31",
    });
  });
});

describe("ORDERS_NEEDING_ATTENTION", () => {
  it("USES THE LITERAL 'true' THE ENDPOINT TESTS FOR", async () => {
    // The bug this pins: `needs_review=1` is not rejected, it is ignored — so the filter
    // never applies and the count becomes every order. The dashboard rendered "14 orders
    // needing a decision" on a shop with two before this was caught.
    const { ORDERS_NEEDING_ATTENTION } = await import("@/lib/dashboard");

    expect(ORDERS_NEEDING_ATTENTION).toBe("needs_attention=true");
    expect(ORDERS_NEEDING_ATTENTION).not.toContain("needs_review");
  });
});
