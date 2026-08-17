import { describe, it, expect } from "vitest";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY, normalizeCountry, formatMoney, symbolFor } from "@/lib/country";

const MARKETS = ["NG", "GB", "US", "CA", "ZZ"];

describe("country helpers", () => {
  it("exposes the cookie name and NG default", () => {
    expect(COUNTRY_COOKIE).toBe("country");
    expect(DEFAULT_COUNTRY).toBe("NG");
  });

  it("normalizes a known market (case-insensitive)", () => {
    expect(normalizeCountry("gb", MARKETS)).toBe("GB");
  });

  it("falls back to ZZ (rest of world) for an unknown but non-empty code", () => {
    expect(normalizeCountry("FR", MARKETS)).toBe("ZZ");
  });

  it("falls back to the NG default for a missing code", () => {
    expect(normalizeCountry(undefined, MARKETS)).toBe("NG");
  });

  it("formats money per currency", () => {
    expect(formatMoney("12500.00", "NGN")).toBe("₦12,500.00");
    expect(formatMoney("19.99", "GBP")).toBe("£19.99");
  });

  // Regression: formatMoney used to take the symbol as a third argument, and the cart
  // shipped passing "" for it — a number with no currency in front of it. The symbol is
  // now derived from the code, so there is no argument left to get wrong.
  it("always carries a currency marker, even for a code it has no symbol for", () => {
    expect(formatMoney("100.00", "USD")).toBe("$100.00");
    expect(formatMoney("100.00", "CAD")).toBe("CA$100.00");
    expect(formatMoney("100.00", "EUR")).toBe("EUR 100.00");
    expect(formatMoney("100.00", "NGN")).not.toBe("100.00");
  });
});

describe("symbolFor", () => {
  it("maps the four live currencies and falls back to the code", () => {
    expect(symbolFor("NGN")).toBe("₦");
    expect(symbolFor("GBP")).toBe("£");
    expect(symbolFor("USD")).toBe("$");
    expect(symbolFor("CAD")).toBe("CA$");
    expect(symbolFor("EUR")).toBe("EUR ");
  });
});
