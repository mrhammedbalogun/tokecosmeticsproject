import { describe, it, expect } from "vitest";
import {
  ADJUST_REASONS,
  deltaFor,
  hasErrors,
  isAdjustReason,
  REASON_GROUPS,
  validateAdjust,
} from "@/lib/stock-adjust";

const entry = (over: Partial<{ quantity: string; reason: string; note: string }> = {}) => ({
  quantity: "12",
  reason: "adjustment",
  note: "Counted the shelf",
  ...over,
});

describe("the reason list", () => {
  it("NEVER offers `migration`", () => {
    // A machine-only sentinel that apps/migration_wp/importers/stock.py reads to find
    // stock nobody has touched. A human writing it would silently strip that item's
    // clobber guard and expose it to being overwritten by the next migration run.
    expect(ADJUST_REASONS).not.toContain("migration");
    expect(isAdjustReason("migration")).toBe(false);
  });

  it("offers exactly what StockAdjustSerializer accepts", () => {
    expect([...ADJUST_REASONS].sort()).toEqual([
      "adjustment",
      "damaged",
      "release",
      "reservation",
      "restock",
      "returned",
      "sale",
    ]);
  });

  it("groups every reason, so none is silently dropped from the dropdown", () => {
    // A UI offering fewer choices than the endpoint accepts is a UI that disagrees with
    // it. They are separated and labelled instead.
    const grouped = REASON_GROUPS.flatMap((g) => g.reasons).sort();
    expect(grouped).toEqual([...ADJUST_REASONS].sort());
  });

  it("separates the reasons the order flow writes for itself", () => {
    // A human picking `sale` puts a row in the ledger that reads as though an order
    // caused it. Naming that is cheaper than explaining it afterwards.
    const automatic = REASON_GROUPS.find((g) => g.label === "Normally automatic");
    expect(automatic?.reasons.sort()).toEqual(["release", "reservation", "sale"]);
  });
});

describe("validateAdjust", () => {
  it("accepts a straightforward entry", () => {
    expect(hasErrors(validateAdjust(entry()))).toBe(false);
  });

  it("ACCEPTS ZERO, because that is how a sold-out line is recorded", () => {
    // `IntegerField(min_value=0)` — zero is valid and meaningful.
    expect(validateAdjust(entry({ quantity: "0" })).quantity).toBeUndefined();
  });

  it("rejects a blank, negative, decimal or non-numeric count", () => {
    expect(validateAdjust(entry({ quantity: "" })).quantity).toBeDefined();
    expect(validateAdjust(entry({ quantity: "-1" })).quantity).toBeDefined();
    expect(validateAdjust(entry({ quantity: "1.5" })).quantity).toBeDefined();
    expect(validateAdjust(entry({ quantity: "lots" })).quantity).toBeDefined();
  });

  it("rejects the shapes Number() would have accepted", () => {
    // "1e3" and " 1 " parse to numbers but are not counts anybody typed on purpose.
    expect(validateAdjust(entry({ quantity: "1e3" })).quantity).toBeDefined();
  });

  it("REQUIRES A NOTE, and a blank one is not a note", () => {
    // The endpoint's `note` is a bare CharField(), which rejects blank as well as
    // missing. A stock write-off with no stated reason is exactly the row somebody wants
    // to read back a month later.
    expect(validateAdjust(entry({ note: "" })).note).toBeDefined();
    expect(validateAdjust(entry({ note: "   " })).note).toBeDefined();
  });

  it("rejects a reason the endpoint would refuse", () => {
    expect(validateAdjust(entry({ reason: "migration" })).reason).toBeDefined();
    expect(validateAdjust(entry({ reason: "" })).reason).toBeDefined();
  });
});

describe("deltaFor", () => {
  it("reports what the ledger will record", () => {
    // The field is an ABSOLUTE count while the movement stores a difference — "47" means
    // very different things depending on whether the shelf held 12 or 300.
    expect(deltaFor(12, "47")).toBe(35);
    expect(deltaFor(300, "47")).toBe(-253);
  });

  it("is zero for an unchanged count", () => {
    expect(deltaFor(12, "12")).toBe(0);
  });

  it("is null while the entry is not yet a number", () => {
    expect(deltaFor(12, "")).toBeNull();
    expect(deltaFor(12, "4x")).toBeNull();
  });
});
