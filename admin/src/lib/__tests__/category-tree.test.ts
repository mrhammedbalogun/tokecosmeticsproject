import { describe, it, expect } from "vitest";
import { countsByCategory, descendantIds, eligibleParents } from "@/lib/category-tree";
import type { CategoryRef } from "@/lib/reference";

const cat = (id: number, parent: number | null = null, name = `C${id}`): CategoryRef => ({
  id,
  name,
  slug: `c-${id}`,
  parent,
  is_active: true,
  sort_order: 0,
});

/*  1 ─ 2 ─ 4
      └ 3
    5 (root, unrelated)  */
const TREE = [cat(1), cat(2, 1), cat(3, 1), cat(4, 2), cat(5)];

describe("descendantIds", () => {
  it("finds children and grandchildren", () => {
    expect(descendantIds(1, TREE).sort()).toEqual([2, 3, 4]);
  });

  it("is empty for a leaf", () => {
    expect(descendantIds(4, TREE)).toEqual([]);
  });

  it("terminates on a cycle already in the data", () => {
    // The backend now refuses to create one, but a row written before that guard — or
    // straight into the database — must not hang the page that exists to fix the tree.
    const cyclic = [cat(1, 2), cat(2, 1)];

    expect(descendantIds(1, cyclic).length).toBeLessThanOrEqual(2);
  });
});

describe("eligibleParents", () => {
  it("excludes the category itself", () => {
    const ids = eligibleParents(cat(1), TREE).map((c) => c.id);

    expect(ids).not.toContain(1);
  });

  it("EXCLUDES ITS WHOLE SUBTREE, not just its children", () => {
    // A check that only hid direct children would still offer the grandchild, and
    // choosing it makes a cycle — which hangs the storefront's breadcrumb walk and its
    // recursive tree serializer.
    const ids = eligibleParents(TREE[0], TREE).map((c) => c.id);

    expect(ids).toEqual([5]);
  });

  it("offers unrelated categories, including other roots", () => {
    const ids = eligibleParents(TREE[3], TREE).map((c) => c.id);

    expect(ids.sort()).toEqual([1, 2, 3, 5]);
  });

  it("offers a leaf's own ancestors, because moving up the tree is legal", () => {
    // Node 4's parent is 2; reparenting it to 1 is an ordinary move, not a cycle.
    expect(eligibleParents(TREE[3], TREE).map((c) => c.id)).toContain(1);
  });
});

describe("countsByCategory", () => {
  it("counts products per category", () => {
    const counts = countsByCategory([
      { categories: [1, 2] },
      { categories: [1] },
      { categories: [] },
    ]);

    expect(counts.get(1)).toBe(2);
    expect(counts.get(2)).toBe(1);
  });

  it("reports nothing for a category no product uses", () => {
    // Rendered as "0 products", which is the answer to "can I safely hide this?"
    expect(countsByCategory([{ categories: [1] }]).get(9)).toBeUndefined();
  });
});
