import { describe, it, expect } from "vitest";
import { deliveryEstimateFor } from "@/lib/delivery-estimates";

describe("deliveryEstimateFor", () => {
  it("has copy for every live market", () => {
    for (const code of ["NG", "GB", "US", "CA"]) {
      expect(deliveryEstimateFor(code)).toBeTruthy();
    }
  });
  it("falls back to the international line for ZZ/unknown", () => {
    expect(deliveryEstimateFor("ZZ")).toMatch(/international/i);
    expect(deliveryEstimateFor("FR")).toMatch(/international/i);
  });
});
