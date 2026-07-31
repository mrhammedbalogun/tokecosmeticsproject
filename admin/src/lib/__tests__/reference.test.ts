import { describe, it, expect, vi } from "vitest";
import {
  categoryDepth,
  fetchAllPages,
  MAX_PAGES,
  orderCategories,
  type CategoryRef,
} from "@/lib/reference";

const category = (id: number, parent: number | null = null, name = `C${id}`): CategoryRef => ({
  id,
  name,
  slug: `c-${id}`,
  parent,
  is_active: true,
  sort_order: 0,
});

describe("fetchAllPages", () => {
  it("follows every page, because production has more categories than one page holds", async () => {
    // 40 categories at DRF's PAGE_SIZE=24 is two pages. A picker that fetched one would
    // silently omit 16 of them, and the symptom is somebody reporting that a category
    // "does not exist" while it sits in the database.
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce({ count: 3, next: "http://api/x?page=2", results: [1, 2] })
      .mockResolvedValueOnce({ count: 3, next: null, results: [3] });

    const all = await fetchAllPages<number>(fetcher, "/admin/categories/", "/products/x");

    expect(all).toEqual([1, 2, 3]);
    expect(fetcher).toHaveBeenNthCalledWith(1, "/admin/categories/", "/products/x");
    expect(fetcher).toHaveBeenNthCalledWith(2, "/admin/categories/?page=2", "/products/x");
  });

  it("requests pages by number and never by the API's absolute next URL", async () => {
    // `next` points at the Django origin. This app's fetcher takes a path relative to its
    // own API base, so an absolute URL would either fail or bypass the base and address
    // Django directly from the server.
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce({ count: 2, next: "https://api.example.test/v1/x?page=2", results: [1] })
      .mockResolvedValueOnce({ count: 2, next: null, results: [2] });

    await fetchAllPages<number>(fetcher, "/admin/tags/", "/products/x");

    expect(fetcher.mock.calls[1][0]).toBe("/admin/tags/?page=2");
  });

  it("appends the page with & when the path already has a query", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce({ count: 2, next: "next", results: [1] })
      .mockResolvedValueOnce({ count: 2, next: null, results: [2] });

    await fetchAllPages<number>(fetcher, "/admin/tags/?is_active=true", "/x");

    expect(fetcher.mock.calls[1][0]).toBe("/admin/tags/?is_active=true&page=2");
  });

  it("stops at the page cap rather than looping on a malformed next", async () => {
    const fetcher = vi.fn().mockResolvedValue({ count: 1, next: "always", results: [1] });

    const all = await fetchAllPages<number>(fetcher, "/admin/tags/", "/x");

    expect(fetcher).toHaveBeenCalledTimes(MAX_PAGES);
    expect(all).toHaveLength(MAX_PAGES);
  });
});

describe("orderCategories", () => {
  it("puts each child directly under its parent", () => {
    const ordered = orderCategories([category(3, 1), category(1), category(2)]);

    expect(ordered.map((c) => c.id)).toEqual([1, 3, 2]);
  });

  it("keeps an orphan rather than dropping it", () => {
    // A category whose parent was deleted is still a category somebody may need to tick.
    // Hiding it from the picker is worse than listing it last.
    const ordered = orderCategories([category(1), category(9, 404)]);

    expect(ordered.map((c) => c.id)).toEqual([1, 9]);
  });

  it("terminates on a parent cycle instead of hanging the render", () => {
    const a = category(1, 2);
    const b = category(2, 1);

    const ordered = orderCategories([a, b]);

    expect(ordered).toHaveLength(2);
  });
});

describe("categoryDepth", () => {
  it("counts the ancestors", () => {
    const all = [category(1), category(2, 1), category(3, 2)];

    expect(categoryDepth(all[0], all)).toBe(0);
    expect(categoryDepth(all[1], all)).toBe(1);
    expect(categoryDepth(all[2], all)).toBe(2);
  });

  it("stops at a missing parent", () => {
    const orphan = category(9, 404);

    expect(categoryDepth(orphan, [orphan])).toBe(0);
  });

  it("stops on a cycle", () => {
    const all = [category(1, 2), category(2, 1)];

    expect(categoryDepth(all[0], all)).toBeLessThanOrEqual(10);
  });
});
