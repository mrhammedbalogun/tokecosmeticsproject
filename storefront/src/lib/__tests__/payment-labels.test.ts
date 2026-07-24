import { describe, it, expect } from "vitest";
import { paymentLabel } from "@/lib/payment-labels";

describe("paymentLabel", () => {
  it("returns the display name + note for a known gateway", () => {
    const label = paymentLabel("bank_transfer");
    expect(label.name).toBe("Bank transfer");
    expect(label.note).toMatch(/pay by transfer/i);
  });

  it("falls back to the raw code as name + empty note for an unknown gateway", () => {
    const label = paymentLabel("some_future_gateway");
    expect(label.name).toBe("some_future_gateway");
    expect(label.note).toBe("");
  });
});
