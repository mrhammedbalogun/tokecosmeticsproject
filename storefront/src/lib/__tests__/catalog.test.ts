import { describe, it, expect, vi, beforeEach } from "vitest";

// fetchPlpPage → getProducts → apiFetch. Mock apiFetch to drive the 404-swallow
// policy without a network, but keep the REAL ApiError so `instanceof` holds.
vi.mock("@/lib/api", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/api")>();
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch, ApiError } from "@/lib/api";
import {
  buildProductQuery, fetchPlpPage, findCategory, flattenCategories,
  EMPTY_PAGE, type CategoryNode, type Paginated, type ProductCard,
} from "@/lib/catalog";

const mockApiFetch = vi.mocked(apiFetch);

const TREE: CategoryNode[] = [
  { name: "Face", slug: "face", image: null, sort_order: 0, children: [
    { name: "Serums", slug: "serums", image: null, sort_order: 0, children: [
      { name: "Vitamin C", slug: "vitamin-c", image: null, sort_order: 0, children: [] },
    ]},
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
  it("finds a deeply nested node with its FULL ancestor chain in root→parent order", () => {
    const hit = findCategory(TREE, "vitamin-c");
    expect(hit?.node.name).toBe("Vitamin C");
    // Order matters — [root, …, parent]; a reversed chain would break breadcrumbs.
    expect(hit?.ancestors.map((a) => a.slug)).toEqual(["face", "serums"]);
  });
  it("finds a mid-level node with a single ancestor", () => {
    const hit = findCategory(TREE, "serums");
    expect(hit?.ancestors.map((a) => a.slug)).toEqual(["face"]);
  });
  it("gives a root node an empty ancestor chain", () => {
    const hit = findCategory(TREE, "body");
    expect(hit?.node.name).toBe("Body");
    expect(hit?.ancestors).toEqual([]);
  });
  it("returns null for a miss", () => {
    expect(findCategory(TREE, "nope")).toBeNull();
  });
  it("flattens the tree depth-first", () => {
    expect(flattenCategories(TREE).map((c) => c.slug))
      .toEqual(["face", "serums", "vitamin-c", "body"]);
  });
});

describe("fetchPlpPage (shared PLP 404-swallow policy)", () => {
  beforeEach(() => mockApiFetch.mockReset());

  it("passes a successful page through untouched", async () => {
    const page: Paginated<ProductCard> = { count: 1, next: null, previous: null, results: [] };
    mockApiFetch.mockResolvedValueOnce(page);
    await expect(fetchPlpPage({ category: "face" }, "NG")).resolves.toBe(page);
  });

  it("swallows a DRF 404 (out-of-range page) to the empty state", async () => {
    mockApiFetch.mockRejectedValueOnce(new ApiError(404, { detail: "Invalid page." }));
    await expect(fetchPlpPage({ page: 99999 }, "NG")).resolves.toEqual(EMPTY_PAGE);
  });

  it("rethrows a real backend error (5xx) instead of masking it", async () => {
    mockApiFetch.mockRejectedValueOnce(new ApiError(500, {}));
    await expect(fetchPlpPage({}, "NG")).rejects.toBeInstanceOf(ApiError);
  });

  it("rethrows a non-ApiError (e.g. network failure)", async () => {
    mockApiFetch.mockRejectedValueOnce(new Error("network down"));
    await expect(fetchPlpPage({}, "NG")).rejects.toThrow("network down");
  });
});
