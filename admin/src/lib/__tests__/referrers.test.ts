import { describe, it, expect } from "vitest";
import {
  parseReferrerFilters,
  referrersQueryString,
  signedAmount,
} from "@/lib/referrals";

describe("referrer filters", () => {
  it("only sends the blocked filter when it is actually on", () => {
    // "false" would filter nobody out and come back looking unfiltered, which reads as a
    // broken checkbox rather than as an empty result.
    expect(referrersQueryString({ blocked: "false" })).toBe("");
    expect(referrersQueryString({ blocked: "true" })).toBe("?is_blocked=true");
  });

  it("keeps the search term and page together", () => {
    expect(referrersQueryString({ page: 3, search: "amina" })).toBe("?page=3&search=amina");
  });

  it("treats anything but 'true' as unfiltered", () => {
    expect(parseReferrerFilters({ blocked: "yes" }).blocked).toBe("");
    expect(parseReferrerFilters({ blocked: "true" }).blocked).toBe("true");
  });
});

describe("signedAmount", () => {
  it("keeps the sign impossible to miss", () => {
    // The whole risk of the adjustment screen: crediting what you meant to claw back
    // looks completely normal until somebody reconciles the month.
    expect(signedAmount("NGN", "-2500.00")).toBe("−NGN 2,500.00");
    expect(signedAmount("NGN", "2500.00")).toBe("+NGN 2,500.00");
  });

  it("uses a real minus sign, not a hyphen", () => {
    // U+2212. A hyphen at 12px beside a digit is a smudge.
    expect(signedAmount("GBP", "-20.00").startsWith("−")).toBe(true);
  });
});
