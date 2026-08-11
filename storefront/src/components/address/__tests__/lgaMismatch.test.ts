import { describe, expect, it } from "vitest";
import { detectLgaMismatch, normalizeLgaName } from "@/components/address/lgaMismatch";
import type { Region } from "@/components/checkout/RegionSelect";

const region = (id: number, name: string): Region => ({
  id, name, level: "area", has_children: false,
});

const AREAS = [region(1, "Ikeja"), region(2, "Eti-Osa"), region(3, "Agege")];

describe("normalizeLgaName", () => {
  it("folds Google's suffixes and punctuation into our plain names", () => {
    expect(normalizeLgaName("Ikeja Local Government Area")).toBe("ikeja");
    expect(normalizeLgaName("Eti-Osa")).toBe("eti osa");
    expect(normalizeLgaName("AGEGE LGA")).toBe("agege");
  });
});

describe("detectLgaMismatch", () => {
  it("returns the region Google named when it differs from the selection", () => {
    expect(detectLgaMismatch("Agege Local Government Area", 1, AREAS)).toEqual(AREAS[2]);
  });

  it("stays quiet when the names agree, despite formatting differences", () => {
    expect(detectLgaMismatch("Ikeja Local Government Area", 1, AREAS)).toBeNull();
    expect(detectLgaMismatch("eti-osa", 2, AREAS)).toBeNull();
  });

  it("stays quiet when Google names an LGA we cannot price", () => {
    // Suggesting an area that isn't a selectable region would dead-end the form.
    expect(detectLgaMismatch("Somewhere Unknown", 1, AREAS)).toBeNull();
  });

  it("stays quiet without a pick, a selection, or loaded areas", () => {
    expect(detectLgaMismatch(null, 1, AREAS)).toBeNull();
    expect(detectLgaMismatch("Agege", undefined, AREAS)).toBeNull();
    expect(detectLgaMismatch("Agege", 1, [])).toBeNull();
  });
});
