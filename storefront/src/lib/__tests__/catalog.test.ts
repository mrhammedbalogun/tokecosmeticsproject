import { describe, it, expect } from "vitest";
import { buildProductQuery, findCategory, flattenCategories, type CategoryNode } from "@/lib/catalog";

const TREE: CategoryNode[] = [
  { name: "Face", slug: "face", image: null, sort_order: 0, children: [
    { name: "Serums", slug: "serums", image: null, sort_order: 0, children: [] },
  ]},
  { name: "Body", slug: "body", image: null, sort_order: 1, children: [] },
];

describe("buildProductQuery", () => {
  it("serialises only known, present params in a stable order", () => {
    expect(buildProductQuery({ category: "face", ordering: "price_asc", page: 2 }))
      .toBe("category=face&ordering=price_asc&page=2");
  });
  it("omits page 1 and empty values", () => {
    expect(buildProductQuery({ page: 1, brand: "" })).toBe("");
  });
  it("ignores unknown keys (URL params are user input)", () => {
    // @ts-expect-error — deliberately passing junk
    expect(buildProductQuery({ evil: "1;drop" })).toBe("");
  });
});

describe("category tree helpers", () => {
  it("finds a nested node with its ancestor chain", () => {
    const hit = findCategory(TREE, "serums");
    expect(hit?.node.name).toBe("Serums");
    expect(hit?.ancestors.map((a) => a.slug)).toEqual(["face"]);
  });
  it("returns null for a miss", () => {
    expect(findCategory(TREE, "nope")).toBeNull();
  });
  it("flattens the tree depth-first", () => {
    expect(flattenCategories(TREE).map((c) => c.slug)).toEqual(["face", "serums", "body"]);
  });
});
