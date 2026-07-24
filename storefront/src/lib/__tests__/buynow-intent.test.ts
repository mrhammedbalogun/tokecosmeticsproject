import { describe, it, expect, beforeEach } from "vitest";
import { readBuyNowIntent, clearBuyNowIntent, BUYNOW_INTENT_KEY } from "@/lib/buynow-intent";

describe("buynow-intent", () => {
  beforeEach(() => sessionStorage.clear());
  it("reads a stashed intent", () => {
    sessionStorage.setItem(BUYNOW_INTENT_KEY, JSON.stringify({ variant_id: 5, quantity: 2 }));
    expect(readBuyNowIntent()).toEqual({ variant_id: 5, quantity: 2 });
  });
  it("returns null when absent", () => { expect(readBuyNowIntent()).toBeNull(); });
  it("returns null on corrupt JSON", () => {
    sessionStorage.setItem(BUYNOW_INTENT_KEY, "{not json");
    expect(readBuyNowIntent()).toBeNull();
  });
  it("clear removes it", () => {
    sessionStorage.setItem(BUYNOW_INTENT_KEY, JSON.stringify({ variant_id: 1, quantity: 1 }));
    clearBuyNowIntent();
    expect(readBuyNowIntent()).toBeNull();
  });
});
