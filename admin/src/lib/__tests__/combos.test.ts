import { describe, it, expect } from "vitest";
import {
  autoPrice,
  componentsTotal,
  orderMarkets,
  optionSummary,
  previewPricing,
  roundHalfUp,
} from "@/lib/combos";

const items = [
  { quantity: 1, prices: { NG: "1000.00", GB: "10.00", US: null } },
  { quantity: 2, prices: { NG: "500.00", GB: "5.00", US: "6.00" } },
];

describe("componentsTotal", () => {
  it("multiplies each price by its quantity", () => {
    expect(componentsTotal(items, "NG")).toBe(2000);
    expect(componentsTotal(items, "GB")).toBe(20);
  });

  it("is null when ANY component is unpriced — unpriceable, not cheap", () => {
    expect(componentsTotal(items, "US")).toBeNull();
  });

  it("is null for an empty box", () => {
    expect(componentsTotal([], "NG")).toBeNull();
  });

  it("is null for a market nothing is priced in", () => {
    expect(componentsTotal(items, "CA")).toBeNull();
  });
});

describe("autoPrice + roundHalfUp", () => {
  it("takes the discount off the total", () => {
    expect(autoPrice(2000, 10)).toBe(1800);
    expect(autoPrice(2000, 0)).toBe(2000);
  });

  it("rounds half UP, matching the backend's q2 rather than toFixed", () => {
    // 18.005 lands at 1800.4999999999998 when naively scaled; the epsilon absorbs it.
    expect(roundHalfUp(18.005)).toBe(18.01);
    expect(roundHalfUp(1.005)).toBe(1.01);
    expect(roundHalfUp(2.675)).toBe(2.68);
  });
});

describe("previewPricing", () => {
  it("prefills every market at the discount and reports the saving", () => {
    const [ng, gb] = previewPricing(items, ["NG", "GB"], 10, {});
    expect(ng).toMatchObject({ componentsTotal: 2000, amount: 1800, saving: 200, savingPercent: 10, pinned: false });
    expect(gb).toMatchObject({ componentsTotal: 20, amount: 18, saving: 2, pinned: false });
  });

  it("a typed override pins the market and reports the REAL percentage", () => {
    const [ng] = previewPricing(items, ["NG"], 10, { NG: "1500" });
    expect(ng.pinned).toBe(true);
    expect(ng.amount).toBe(1500);
    expect(ng.savingPercent).toBe(25);
  });

  it("clamps a pin above the component total, as the server does", () => {
    // Otherwise the preview shows a negative saving where the server would show zero.
    const [ng] = previewPricing(items, ["NG"], 10, { NG: "9999" });
    expect(ng.amount).toBe(2000);
    expect(ng.saving).toBe(0);
  });

  it("clamps a negative pin to zero", () => {
    const [ng] = previewPricing(items, ["NG"], 10, { NG: "-50" });
    expect(ng.amount).toBe(0);
  });

  it("an empty box is not a pin — a blank field means automatic", () => {
    const [ng] = previewPricing(items, ["NG"], 10, { NG: "" });
    expect(ng.pinned).toBe(false);
    expect(ng.amount).toBe(1800);
  });

  it("reports an unpriceable market with nulls rather than a partial sum", () => {
    const [us] = previewPricing(items, ["US"], 10, {});
    expect(us.componentsTotal).toBeNull();
    expect(us.amount).toBeNull();
  });
});

describe("orderMarkets", () => {
  it("keeps the known order, then anything else alphabetically", () => {
    expect(orderMarkets(["US", "NG", "ZA", "GB"])).toEqual(["NG", "GB", "US", "ZA"]);
  });
});

describe("optionSummary", () => {
  it("joins the chosen options", () => {
    expect(optionSummary({ Size: "500g", Pack: "Pieces" }, "x")).toBe("500g · Pieces");
  });

  it("falls back to the variant name when there are no options", () => {
    expect(optionSummary({}, "Default")).toBe("Default");
  });
});
