import { describe, it, expect } from "vitest";
import {
  amountChanged,
  buildPriceGrid,
  missingCount,
  validateAmount,
  type Cell,
  type PriceRow,
  type VariantRow,
} from "@/lib/product-prices";

const CURRENCIES = ["NGN", "GBP", "USD", "CAD"];

const variant = (id: number, sku = `SKU-${id}`): VariantRow => ({
  id,
  sku,
  name: `${id}ml`,
  weight_grams: 250,
  is_active: true,
  position: 0,
  option_values: {},
});

const price = (overrides: Partial<PriceRow> & { variant: number }): PriceRow => ({
  id: 1,
  currency: "NGN",
  country: null,
  amount: "5000.00",
  starts_at: null,
  ends_at: null,
  ...overrides,
});

describe("buildPriceGrid", () => {
  it("is one row per VARIANT, not per currency", () => {
    // Price hangs off ProductVariant. "A row per currency" would be right for the 51
    // single-variant products and wrong for the 18 that are not.
    const grid = buildPriceGrid([variant(1), variant(2)], [], CURRENCIES);

    expect(grid).toHaveLength(2);
    expect(Object.keys(grid[0].cells)).toEqual(CURRENCIES);
  });

  it("fills a cell from its currency-level row", () => {
    const grid = buildPriceGrid([variant(1)], [price({ variant: 1, amount: "1500.00" })], CURRENCIES);

    expect(grid[0].cells.NGN.state).toBe("editable");
    expect(grid[0].cells.NGN.amount).toBe("1500.00");
  });

  it("leaves an unpriced cell editable and empty", () => {
    const grid = buildPriceGrid([variant(1)], [], CURRENCIES);

    expect(grid[0].cells.GBP).toEqual({ state: "editable", price: null, amount: "" });
  });

  it("does not let one variant's price leak into another's row", () => {
    const grid = buildPriceGrid(
      [variant(1), variant(2)],
      [price({ variant: 1, amount: "1500.00" })],
      CURRENCIES,
    );

    expect(grid[1].cells.NGN.amount).toBe("");
  });

  // --- the locked-cell rule ----------------------------------------------------------

  it("LOCKS a cell that has a country override, and names the country", () => {
    // The worst bug this screen can have: silently showing the plain row while a narrower
    // one governs a market means an edit that appears to succeed and changes nothing.
    const grid = buildPriceGrid(
      [variant(1)],
      [
        price({ variant: 1, id: 1, amount: "1500.00" }),
        price({ variant: 1, id: 2, amount: "1200.00", country: "GB", currency: "NGN" }),
      ],
      CURRENCIES,
    );

    const cell = grid[0].cells.NGN;
    expect(cell.state).toBe("locked");
    expect(cell.state === "locked" && cell.reason).toContain("GB");
    // The message must STOP rather than promise a slice nobody intends to build (17c
    // ruling 4), and must not hint at hand-editing the database either.
    expect(cell.state === "locked" && cell.reason).toContain("cannot be edited here");
    expect(cell.state === "locked" && cell.reason).not.toContain("17c");
    expect(cell.state === "locked" && cell.reason).not.toMatch(/database/i);
  });

  it("names every country when more than one override exists", () => {
    const grid = buildPriceGrid(
      [variant(1)],
      [
        price({ variant: 1, id: 1, amount: "1200.00", country: "GB" }),
        price({ variant: 1, id: 2, amount: "1300.00", country: "US" }),
      ],
      CURRENCIES,
    );

    const cell = grid[0].cells.NGN;
    expect(cell.state === "locked" && cell.reason).toContain("GB, US");
  });

  it("LOCKS a cell that has a scheduled price", () => {
    // The unique constraint is (variant, currency, country, starts_at), so a second
    // currency-level row with a start date is legal — and may be the one in effect.
    const grid = buildPriceGrid(
      [variant(1)],
      [
        price({ variant: 1, id: 1, amount: "1500.00" }),
        price({ variant: 1, id: 2, amount: "1800.00", starts_at: "2026-12-01T00:00:00Z" }),
      ],
      CURRENCIES,
    );

    const cell = grid[0].cells.NGN;
    expect(cell.state).toBe("locked");
    expect(cell.state === "locked" && cell.reason).toMatch(/scheduled/i);
  });

  it("still SHOWS the plain amount on a locked cell rather than hiding it", () => {
    // Read-only, but visible. A blank locked cell would read as "no price set".
    const grid = buildPriceGrid(
      [variant(1)],
      [
        price({ variant: 1, id: 1, amount: "1500.00" }),
        price({ variant: 1, id: 2, amount: "1200.00", country: "GB" }),
      ],
      CURRENCIES,
    );

    expect(grid[0].cells.NGN.amount).toBe("1500.00");
  });

  it("locks only the affected currency, not the whole row", () => {
    const grid = buildPriceGrid(
      [variant(1)],
      [price({ variant: 1, id: 2, amount: "40.00", currency: "GBP", country: "GB" })],
      CURRENCIES,
    );

    expect(grid[0].cells.GBP.state).toBe("locked");
    expect(grid[0].cells.NGN.state).toBe("editable");
  });

  it("locks a cell that has ONLY an override and no plain row", () => {
    const grid = buildPriceGrid(
      [variant(1)],
      [price({ variant: 1, id: 2, amount: "40.00", currency: "GBP", country: "GB" })],
      CURRENCIES,
    );

    expect(grid[0].cells.GBP.price).toBeNull();
    expect(grid[0].cells.GBP.state).toBe("locked");
  });
});

describe("missingCount", () => {
  it("counts the cells with no price at all", () => {
    // Production is NGN-only: 121 prices, all one currency. Three quarters of every grid.
    const grid = buildPriceGrid([variant(1)], [price({ variant: 1 })], CURRENCIES);

    expect(missingCount(grid, CURRENCIES)).toBe(3);
  });

  it("is zero when everything is priced", () => {
    const grid = buildPriceGrid(
      [variant(1)],
      CURRENCIES.map((currency, i) => price({ variant: 1, id: i + 1, currency })),
      CURRENCIES,
    );

    expect(missingCount(grid, CURRENCIES)).toBe(0);
  });
});

describe("validateAmount", () => {
  it("accepts a plain amount and two decimals", () => {
    expect(validateAmount("1500")).toBeNull();
    expect(validateAmount("1500.00")).toBeNull();
    expect(validateAmount("0.50")).toBeNull();
  });

  it("treats blank as 'leave it alone' rather than invalid", () => {
    // Clearing a price is a DELETE, which 17a does not do.
    expect(validateAmount("")).toBeNull();
    expect(validateAmount("   ")).toBeNull();
  });

  it("REJECTS a thousands separator instead of guessing", () => {
    // "1,500" is 1500 to a Nigerian reader and 1.5 to a German one. Guessing wrong writes
    // a price off by a factor of a thousand.
    expect(validateAmount("1,500")).toMatch(/dot/i);
  });

  it("rejects letters, negatives, zero and three decimals", () => {
    expect(validateAmount("abc")).not.toBeNull();
    expect(validateAmount("-5")).not.toBeNull();
    expect(validateAmount("0")).not.toBeNull();
    expect(validateAmount("1.234")).not.toBeNull();
  });
});

describe("amountChanged", () => {
  const editable = (amount: string, id: number | null = 1): Cell => ({
    state: "editable",
    price: id === null ? null : price({ variant: 1, id, amount }),
    amount,
  });

  it("is false for an untouched value", () => {
    expect(amountChanged(editable("1500.00"), "1500.00")).toBe(false);
  });

  it("is false for the same number written differently", () => {
    // "1500" against a stored "1500.00" is not an edit, and writing it would cost a
    // request and an audit row for nothing.
    expect(amountChanged(editable("1500.00"), "1500")).toBe(false);
  });

  it("is true for a real change", () => {
    expect(amountChanged(editable("1500.00"), "1600")).toBe(true);
  });

  it("is true for the first price on an empty cell", () => {
    expect(amountChanged(editable("", null), "1500")).toBe(true);
  });

  it("is false for a blank draft, so an emptied box writes nothing", () => {
    expect(amountChanged(editable("1500.00"), "")).toBe(false);
  });
});
