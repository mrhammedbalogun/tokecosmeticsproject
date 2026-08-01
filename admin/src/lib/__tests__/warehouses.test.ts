import { describe, it, expect } from "vitest";
import {
  duplicatePriorities,
  needsCoverageConfirmation,
  strandedCountries,
  warehousesAtPriority,
  type WarehouseRow,
} from "@/lib/warehouses";

const wh = (over: Partial<WarehouseRow> = {}): WarehouseRow => ({
  id: 1,
  name: "Lagos HQ",
  location_country: "NG",
  serves_countries: ["NG", "ZZ"],
  priority: 1,
  is_active: true,
  countries_left_unserved: [],
  ...over,
});

/** Production, as measured 2026-07-31: both warehouses active, both at priority 1. */
const LAGOS = wh({ id: 1, name: "Lagos HQ", serves_countries: ["NG", "ZZ"], priority: 1 });
const UK = wh({
  id: 2,
  name: "UK Warehouse",
  location_country: "GB",
  serves_countries: ["GB", "US", "CA", "ZZ"],
  priority: 1,
});

describe("strandedCountries", () => {
  it("NAMES THE MARKET THAT WOULD LOSE ITS LAST WAREHOUSE", () => {
    // The whole reason ruling 1b exists: this edit looks like a checkbox and behaves
    // like a kill switch for Nigerian checkout.
    const stranded = strandedCountries(
      { id: 1, serves_countries: ["ZZ"], is_active: true },
      [LAGOS, UK],
    );

    expect(stranded).toEqual(["NG"]);
  });

  it("says nothing when another ACTIVE warehouse still covers the country", () => {
    // ZZ is served by both, so Lagos dropping it strands nobody.
    expect(
      strandedCountries({ id: 1, serves_countries: ["NG"], is_active: true }, [LAGOS, UK]),
    ).toEqual([]);
  });

  it("DOES NOT COUNT AN INACTIVE WAREHOUSE AS COVER", () => {
    // `reserve()` skips inactive warehouses, so counting one would make the
    // confirmation reassure and be wrong.
    const mothballed = wh({ id: 2, name: "Mothballed", serves_countries: ["NG"], is_active: false });

    expect(
      strandedCountries({ id: 1, serves_countries: [], is_active: true }, [LAGOS, mothballed]),
    ).toEqual(["NG", "ZZ"]);
  });

  it("treats DEACTIVATION as dropping every country it serves", () => {
    expect(
      strandedCountries({ id: 1, serves_countries: ["NG", "ZZ"], is_active: false }, [LAGOS, UK]),
    ).toEqual(["NG"]);
  });

  it("is silent for an edit that only adds coverage", () => {
    expect(
      strandedCountries({ id: 1, serves_countries: ["NG", "ZZ", "GB"], is_active: true }, [LAGOS, UK]),
    ).toEqual([]);
  });

  it("gates the confirmation on the same answer", () => {
    expect(
      needsCoverageConfirmation({ id: 1, serves_countries: ["ZZ"], is_active: true }, [LAGOS, UK]),
    ).toBe(true);
    expect(
      needsCoverageConfirmation({ id: 1, serves_countries: ["NG", "ZZ"], is_active: true }, [LAGOS, UK]),
    ).toBe(false);
  });
});

describe("duplicatePriorities", () => {
  it("FINDS THE TIE NOBODY CHOSE", () => {
    // Production ships both warehouses at priority 1, so allocation falls back to
    // primary-key order — an unset dial, not a decision.
    expect(duplicatePriorities([LAGOS, UK])).toEqual([1]);
    expect(warehousesAtPriority([LAGOS, UK], 1).map((w) => w.name)).toEqual([
      "Lagos HQ",
      "UK Warehouse",
    ]);
  });

  it("ignores inactive warehouses, which allocation never reaches", () => {
    const idle = wh({ id: 3, name: "Idle", priority: 1, is_active: false });

    expect(duplicatePriorities([LAGOS, idle])).toEqual([]);
  });

  it("says nothing once the priorities are distinct", () => {
    expect(duplicatePriorities([LAGOS, { ...UK, priority: 2 }])).toEqual([]);
  });
});
