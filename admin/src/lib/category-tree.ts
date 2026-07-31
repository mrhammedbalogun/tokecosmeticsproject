/**
 * Tree shaping for the categories page.
 *
 * `orderCategories` and `categoryDepth` in `lib/reference.ts` already flatten a category
 * list parent-first for the product editor's picker. This adds the one thing the
 * categories PAGE needs on top: which categories a given category may legally be parented
 * to.
 */
import { categoryDepth, orderCategories, type CategoryRef } from "@/lib/reference";

export { categoryDepth, orderCategories };
export type { CategoryRef };

/**
 * The categories that may be offered as a parent for `category`.
 *
 * Excludes the category itself and everything beneath it — those are precisely the
 * choices that would put a category inside its own subtree.
 *
 * THIS IS A COURTESY, NOT THE CONTROL. `CategoryAdminSerializer.validate_parent` refuses
 * the same moves server-side, and it has to: a select constrains a browser, not a caller,
 * and a cycle hangs the storefront's breadcrumb walk and its recursive tree serializer.
 * Hiding the options here just means nobody has to discover that by being refused.
 */
export function eligibleParents(
  category: CategoryRef,
  all: CategoryRef[],
): CategoryRef[] {
  const banned = new Set<number>([category.id, ...descendantIds(category.id, all)]);
  return all.filter((c) => !banned.has(c.id));
}

/** Every id beneath `rootId`, however deep. */
export function descendantIds(rootId: number, all: CategoryRef[]): number[] {
  const childrenOf = new Map<number | null, CategoryRef[]>();
  for (const c of all) {
    const list = childrenOf.get(c.parent) ?? [];
    list.push(c);
    childrenOf.set(c.parent, list);
  }

  const out: number[] = [];
  const seen = new Set<number>();
  const walk = (id: number) => {
    for (const child of childrenOf.get(id) ?? []) {
      // `seen` terminates on a cycle that is ALREADY in the data. The backend now
      // refuses to create one, but a row written before that guard existed would
      // otherwise hang this walk — and hanging the page that exists to fix the tree
      // would be a poor joke.
      if (seen.has(child.id)) continue;
      seen.add(child.id);
      out.push(child.id);
      walk(child.id);
    }
  };
  walk(rootId);
  return out;
}

/** How many products sit in each category, keyed by id — for the tree's counts. */
export function countsByCategory(
  products: { categories: number[] }[],
): Map<number, number> {
  const counts = new Map<number, number>();
  for (const product of products) {
    for (const id of product.categories) counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  return counts;
}
