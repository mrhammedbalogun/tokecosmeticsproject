/**
 * Reference data the product editor's pickers need: categories, tags, countries.
 *
 * ── WHY THERE IS A PAGE-FOLLOWING FETCHER HERE ──────────────────────────────────────
 *
 * `/admin/categories/` and `/admin/tags/` are paginated at DRF's global `PAGE_SIZE = 24`,
 * and production holds **40 categories** and **~84 tags**. A picker that fetched one page
 * would silently offer the first 24 and omit the rest — and the symptom is somebody
 * reporting that a category "does not exist" while it sits in the database.
 *
 * The alternative was adding `page_size_query_param` to the global pagination class, which
 * changes the contract of every endpoint in the project including the public ones. Two
 * extra server-side requests on an editor load is the smaller change by a wide margin.
 *
 * `/meta/countries/` has `pagination_class = None` (`apps/core/views.py:46`) and returns a
 * bare array, so it needs none of this.
 */
import type { fetchWithAuthOrBounce } from "@/lib/session";

export interface CategoryRef {
  id: number;
  name: string;
  slug: string;
  parent: number | null;
  is_active: boolean;
  sort_order: number;
}

export interface TagRef {
  id: number;
  name: string;
  slug: string;
}

export interface CountryRef {
  code: string;
  name: string;
  is_rest_of_world: boolean;
}

interface Paged<T> {
  count: number;
  next: string | null;
  results: T[];
}

/** The maximum pages we will walk. 40 categories is 2 and ~84 tags is 4; twenty is far
 *  past any real catalogue and stops a malformed `next` from looping forever. */
export const MAX_PAGES = 20;

type Fetcher = typeof fetchWithAuthOrBounce;

/**
 * Every page of a paginated admin list, concatenated.
 *
 * Pages are requested by NUMBER rather than by following the API's absolute `next` URL.
 * `next` points at the Django origin, and this app's fetcher takes a path relative to its
 * own API base — handing it an absolute URL would either fail or, worse, bypass the base
 * and address Django directly from the server. The page number is the portable part.
 */
export async function fetchAllPages<T>(
  fetcher: Fetcher,
  path: string,
  bouncePath: string,
): Promise<T[]> {
  const out: T[] = [];
  for (let page = 1; page <= MAX_PAGES; page++) {
    const sep = path.includes("?") ? "&" : "?";
    const url = page === 1 ? path : `${path}${sep}page=${page}`;
    const body = await fetcher<Paged<T>>(url, bouncePath);
    out.push(...body.results);
    if (!body.next) break;
  }
  return out;
}

/** Categories as a flat list ordered for a picker: parents before their children, each
 *  child directly under its parent. The API returns them by `sort_order, name`, which is
 *  right within a level and meaningless across levels. */
export function orderCategories(categories: CategoryRef[]): CategoryRef[] {
  const byParent = new Map<number | null, CategoryRef[]>();
  for (const c of categories) {
    const siblings = byParent.get(c.parent) ?? [];
    siblings.push(c);
    byParent.set(c.parent, siblings);
  }

  const out: CategoryRef[] = [];
  const seen = new Set<number>();
  const walk = (parent: number | null, depth: number) => {
    // Depth guard, not decoration: `parent` is a self-FK and a cycle introduced by a bad
    // edit would otherwise hang the render rather than show a wrong tree.
    if (depth > 10) return;
    for (const c of byParent.get(parent) ?? []) {
      if (seen.has(c.id)) continue;
      seen.add(c.id);
      out.push(c);
      walk(c.id, depth + 1);
    }
  };
  walk(null, 0);

  // Anything unreachable from a root — an orphan whose parent was deleted, or a member of
  // a cycle — is appended rather than dropped. A picker that hides a category is worse
  // than one that lists it out of order.
  for (const c of categories) if (!seen.has(c.id)) out.push(c);
  return out;
}

/** How deep a category sits, for indenting the picker. */
export function categoryDepth(category: CategoryRef, all: CategoryRef[]): number {
  const byId = new Map(all.map((c) => [c.id, c]));
  let depth = 0;
  let node = category;
  while (node.parent !== null && depth < 10) {
    const parent = byId.get(node.parent);
    if (!parent) break;
    node = parent;
    depth++;
  }
  return depth;
}
