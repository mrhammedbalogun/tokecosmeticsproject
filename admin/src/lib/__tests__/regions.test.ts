import { describe, it, expect } from "vitest";
import { buildTree, coversAddress, stateSelection, type RegionRow } from "@/lib/regions";

const region = (id: number, name: string, level: "state" | "area", parent: number | null = null): RegionRow => ({
  id, country_code: "NG", name, level, parent, is_active: true,
});

const LAGOS = region(1, "Lagos", "state");
const IKEJA = region(2, "Ikeja", "area", 1);
const ETI_OSA = region(3, "Eti-Osa", "area", 1);
const ABUJA = region(4, "Abuja", "state");

describe("buildTree", () => {
  it("nests areas under their state, both alphabetical", () => {
    const tree = buildTree([IKEJA, LAGOS, ABUJA, ETI_OSA]);

    expect(tree.map((n) => n.state.name)).toEqual(["Abuja", "Lagos"]);
    expect(tree[1].areas.map((a) => a.name)).toEqual(["Eti-Osa", "Ikeja"]);
  });

  it("ignores an orphan area rather than crashing on it", () => {
    expect(buildTree([region(9, "Orphan", "area", 999), LAGOS])).toHaveLength(1);
  });
});

describe("stateSelection", () => {
  const node = { state: LAGOS, areas: [IKEJA, ETI_OSA] };

  it("is ALL when the state itself is selected, whatever the areas say", () => {
    expect(stateSelection(node, new Set([LAGOS.id]))).toBe("all");
  });

  it("IS 'SOME' FOR A PARTIAL PICK — which is how mixed granularity stays visible", () => {
    expect(stateSelection(node, new Set([IKEJA.id]))).toBe("some");
  });

  it("is all when every area is picked individually", () => {
    expect(stateSelection(node, new Set([IKEJA.id, ETI_OSA.id]))).toBe("all");
  });

  it("is none when nothing is picked", () => {
    expect(stateSelection(node, new Set())).toBe("none");
  });
});

describe("coversAddress", () => {
  const at = (stateId: number | null, areaId: number | null) => ({
    countryCode: "NG", stateId, areaId,
  });

  it("matches on the whole country", () => {
    expect(coversAddress(at(1, 2), { countryCodes: ["NG"], regionIds: new Set() })).toBe(true);
  });

  it("matches an area through its STATE, mirroring the backend's ancestor walk", () => {
    expect(coversAddress(at(1, 2), { countryCodes: [], regionIds: new Set([1]) })).toBe(true);
  });

  it("matches an exact area", () => {
    expect(coversAddress(at(1, 2), { countryCodes: [], regionIds: new Set([2]) })).toBe(true);
  });

  it("REFUSES an address in a state the option does not serve", () => {
    expect(coversAddress(at(4, null), { countryCodes: [], regionIds: new Set([1]) })).toBe(false);
  });
});
