import { describe, expect, it } from "vitest";
import { rowCollection, type HomepagePayload } from "@/lib/cms";

/** The homepage product rows' collection choices (Phase 3, 2026-08-06): a
 * `collection_carousel` section with `config: {row, collection}` overrides a row's
 * built-in slug; anything less well-formed must fall back, never blank the row. */

const payload = (sections: HomepagePayload["sections"]): HomepagePayload => ({
  sections,
  banners: [],
});

describe("rowCollection", () => {
  it("returns the built-in slug when the CMS says nothing", () => {
    expect(rowCollection(null, "loved", "best-sellers")).toBe("best-sellers");
    expect(rowCollection(payload([]), "natural", "new-arrivals")).toBe("new-arrivals");
  });

  it("reads the admin's override for the matching row only", () => {
    const p = payload([
      { id: 1, type: "collection_carousel", sort: 6, config: { row: "loved", collection: "glow-naturally" } },
    ]);
    expect(rowCollection(p, "loved", "best-sellers")).toBe("glow-naturally");
    expect(rowCollection(p, "natural", "new-arrivals")).toBe("new-arrivals");
  });

  it("ignores malformed sections — wrong type, missing or empty collection", () => {
    const p = payload([
      { id: 1, type: "editorial", sort: 0, config: { row: "loved", collection: "x" } },
      { id: 2, type: "collection_carousel", sort: 6, config: { row: "loved", collection: "" } },
      { id: 3, type: "collection_carousel", sort: 7, config: { row: "loved" } },
    ]);
    expect(rowCollection(p, "loved", "best-sellers")).toBe("best-sellers");
  });
});
