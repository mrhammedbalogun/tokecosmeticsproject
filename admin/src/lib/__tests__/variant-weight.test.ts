import { describe, expect, it } from "vitest";
import { isValidWeightGrams, parseWeightInput, WEIGHT_MAX_GRAMS } from "@/lib/variant-weight";

describe("parseWeightInput", () => {
  it("blank clears the weight rather than writing 0", () => {
    expect(parseWeightInput("")).toEqual({ ok: true, grams: null });
    expect(parseWeightInput("   ")).toEqual({ ok: true, grams: null });
  });

  it("digits become integer grams", () => {
    expect(parseWeightInput("250")).toEqual({ ok: true, grams: 250 });
    expect(parseWeightInput(" 1750 ")).toEqual({ ok: true, grams: 1750 });
  });

  it("refuses 0 — a parcel cannot weigh nothing, blank means unknown", () => {
    expect(parseWeightInput("0").ok).toBe(false);
  });

  it("refuses non-digits, decimals and negatives", () => {
    for (const bad of ["250g", "1.5", "-3", "1e3", "0x10", "two"]) {
      expect(parseWeightInput(bad).ok, bad).toBe(false);
    }
  });

  it("refuses anything over the tonne ceiling", () => {
    expect(parseWeightInput(String(WEIGHT_MAX_GRAMS)).ok).toBe(true);
    expect(parseWeightInput(String(WEIGHT_MAX_GRAMS + 1)).ok).toBe(false);
  });
});

describe("isValidWeightGrams", () => {
  it("accepts null (clear) and positive integers in range", () => {
    expect(isValidWeightGrams(null)).toBe(true);
    expect(isValidWeightGrams(1)).toBe(true);
    expect(isValidWeightGrams(WEIGHT_MAX_GRAMS)).toBe(true);
  });

  it("refuses 0, negatives, fractions and out-of-range values", () => {
    expect(isValidWeightGrams(0)).toBe(false);
    expect(isValidWeightGrams(-1)).toBe(false);
    expect(isValidWeightGrams(2.5)).toBe(false);
    expect(isValidWeightGrams(WEIGHT_MAX_GRAMS + 1)).toBe(false);
  });
});
