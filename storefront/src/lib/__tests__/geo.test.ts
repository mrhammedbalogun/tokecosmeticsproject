import { describe, it, expect } from "vitest";
import { suggestionFor } from "@/lib/geo";

const MARKETS = ["NG", "GB", "US", "CA", "ZZ"];

describe("suggestionFor", () => {
  it("suggests nothing when the user already has a country cookie", () => {
    expect(suggestionFor("GB", "NG", MARKETS)).toBeNull();
  });
  it("keeps the existing cookie even when geo points at a different real market", () => {
    // Isolates the cookie guard: geo is a valid, non-default market, so only the
    // existing-cookie short-circuit can produce null here.
    expect(suggestionFor("US", "GB", MARKETS)).toBeNull();
  });
  it("suggests the geo market when it is a real market and differs from the default", () => {
    expect(suggestionFor(undefined, "GB", MARKETS)).toBe("GB");
  });
  it("suggests nothing when geo equals the NG default", () => {
    expect(suggestionFor(undefined, "NG", MARKETS)).toBeNull();
  });
  it("suggests ZZ for an unknown geo country (international)", () => {
    expect(suggestionFor(undefined, "FR", MARKETS)).toBe("ZZ");
  });
  it("suggests nothing when geo is absent", () => {
    expect(suggestionFor(undefined, undefined, MARKETS)).toBeNull();
  });
});
