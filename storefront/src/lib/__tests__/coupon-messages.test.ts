import { describe, it, expect } from "vitest";
import { couponMessage } from "@/lib/coupon-messages";

describe("couponMessage", () => {
  it("maps known codes to specific copy", () => {
    expect(couponMessage("not_found")).toMatch(/valid/i);
    expect(couponMessage("expired")).toMatch(/expired/i);
    expect(couponMessage("min_not_met")).toMatch(/minimum/i);
  });

  it("has a safe fallback for unknown codes", () => {
    expect(couponMessage("something_new")).toMatch(/couldn.t apply|try again/i);
  });
});
