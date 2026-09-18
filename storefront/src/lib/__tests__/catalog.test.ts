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
  getBrands, getCategoryTree, getCollection, getProduct, getProducts, getReviews,
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
  // Block body: `mockReset()` returns the mock, and vitest treats a function returned
  // from `beforeEach` as a teardown callback — so the concise form calls the mock again
  // after every test. Harmless while every implementation here resolves; it fails the
  // whole file the day one of them rejects.
  beforeEach(() => {
    mockApiFetch.mockReset();
  });

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

describe("catalogue cache configuration", () => {
  // The TTL and the tags are one decision, so they are asserted together. 300s is only
  // affordable BECAUSE Django flushes these tags on every catalogue write
  // (`apps/catalog/revalidate.py`); if a future change drops a tag, the number beside it
  // silently becomes a five-minute staleness bug rather than a backstop.
  const nextOf = () => (mockApiFetch.mock.calls[0][1] as {
    next: { revalidate: number; tags: string[] };
  }).next;

  beforeEach(() => { mockApiFetch.mockReset(); mockApiFetch.mockResolvedValue({}); });

  it("lists products for 300s under the catalog tag", async () => {
    await getProducts({ category: "face" }, "NG");
    expect(nextOf()).toEqual({ revalidate: 300, tags: ["catalog"] });
  });

  it("tags a product page with BOTH catalog and its own slug", async () => {
    // Both, not one: the grid is fetched as ["catalog"] and this page as
    // ["catalog", "product:<slug>"], so a price edit has to reach the grid as well.
    await getProduct("glow-serum", "NG");
    expect(nextOf()).toEqual({
      revalidate: 300, tags: ["catalog", "product:glow-serum"],
    });
  });

  it("keeps the product tag SPECIFIC to the slug asked for", async () => {
    await getProduct("another-product", "NG");
    expect(nextOf().tags).toContain("product:another-product");
    expect(nextOf().tags).not.toContain("product:glow-serum");
  });

  it("reviews stay on their own 300s window under the product tag", async () => {
    // Untouched by the catalogue TTL change — a different fetch with a different tag set.
    await getReviews("glow-serum");
    expect(nextOf()).toEqual({ revalidate: 300, tags: ["product:glow-serum"] });
  });

  it.each([
    ["category tree", () => getCategoryTree("NG")],
    ["brands", () => getBrands("NG")],
    ["collection", () => getCollection("best", "NG")],
  ])("%s keeps its hour-long window under the catalog tag", async (_name, call) => {
    // These were never 60s and must not be dragged to 300 by the constant's change.
    await call();
    expect(nextOf()).toEqual({ revalidate: 3600, tags: ["catalog"] });
  });
});
