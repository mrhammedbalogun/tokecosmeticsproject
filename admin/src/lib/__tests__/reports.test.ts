import { describe, it, expect } from "vitest";
import {
  columnsOf, defaultRange, humanise, isoDate, isReportKey, renderCell, REPORTS,
} from "@/lib/reports";

describe("the report vocabulary", () => {
  it("only accepts names the backend serves", () => {
    expect(isReportKey("revenue")).toBe(true);
    expect(isReportKey("everything")).toBe(false);
  });

  it("marks which report names customers, because exporting it is gated higher", () => {
    const top = REPORTS.find((r) => r.key === "top_customers");
    expect(top?.namesCustomers).toBe(true);
    expect(REPORTS.filter((r) => r.namesCustomers)).toHaveLength(1);
  });
});

describe("defaultRange", () => {
  it("is the last 30 days INCLUSIVE, matching the backend's own default", () => {
    const { start, end } = defaultRange(new Date(2026, 7, 30));
    expect(end).toBe("2026-08-30");
    expect(start).toBe("2026-08-01");
  });

  it("formats in local time, not UTC — a date input has no timezone", () => {
    expect(isoDate(new Date(2026, 0, 5))).toBe("2026-01-05");
  });
});

describe("table rendering", () => {
  it("derives columns from the rows so they cannot drift from the query", () => {
    expect(columnsOf([{ currency: "NGN", gross: "1" }])).toEqual(["currency", "gross"]);
    expect(columnsOf([])).toEqual([]);
  });

  it("RENDERS A NULL CATEGORY AS 'Unattributed', never as blank", () => {
    // The unattributed bucket is the whole reason the category total reconciles; a blank
    // cell would read as a rendering bug and invite someone to 'fix' it away.
    expect(renderCell(null)).toBe("Unattributed");
    expect(renderCell("")).toBe("Unattributed");
  });

  it("humanises keys for display only", () => {
    expect(humanise("order__currency_id")).toBe("Order  currency");
    expect(humanise("lifetime_value")).toBe("Lifetime value");
  });
});
