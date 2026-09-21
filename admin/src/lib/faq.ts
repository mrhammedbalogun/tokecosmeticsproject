/** Shapes for the FAQ admin screen. Mirrors `cms.FaqCategory` / `cms.FaqItem`. */

export interface FaqCategoryRow {
  id: number;
  name: string;
  slug: string;
  blurb: string;
  sort: number;
  is_active: boolean;
  item_count: number;
}

export interface FaqItemRow {
  id: number;
  category: number;
  category_name: string;
  question: string;
  /** What the editor typed. */
  answer_source: string;
  /** What survived the allow-list, and the only thing the storefront ever renders.
   *  Read-only from the API on purpose — see `FaqItemAdminSerializer`. */
  answer: string;
  sort: number;
  is_published: boolean;
}

/** Questions grouped under their category, in the order the storefront will show them. */
export function groupByCategory(
  categories: FaqCategoryRow[],
  items: FaqItemRow[],
): { category: FaqCategoryRow; items: FaqItemRow[] }[] {
  const byCategory = new Map<number, FaqItemRow[]>();
  for (const item of items) {
    const list = byCategory.get(item.category) ?? [];
    list.push(item);
    byCategory.set(item.category, list);
  }
  return [...categories]
    .sort((a, b) => a.sort - b.sort || a.name.localeCompare(b.name))
    .map((category) => ({
      category,
      items: (byCategory.get(category.id) ?? []).sort(
        (a, b) => a.sort - b.sort || a.id - b.id,
      ),
    }));
}

/**
 * What the shop's visitors can actually see right now.
 *
 * The storefront hides a category with nothing published in it, so "4 categories, 20
 * questions" is not the number that matters — this is. Seeded questions awaiting an
 * answer are the normal state here, and the screen should say so plainly rather than
 * implying the FAQ is finished.
 */
export function publicSummary(
  groups: { category: FaqCategoryRow; items: FaqItemRow[] }[],
): { liveCategories: number; liveQuestions: number; awaiting: number } {
  let liveCategories = 0;
  let liveQuestions = 0;
  let awaiting = 0;
  for (const { category, items } of groups) {
    const published = items.filter((i) => i.is_published).length;
    awaiting += items.length - published;
    liveQuestions += category.is_active ? published : 0;
    if (category.is_active && published > 0) liveCategories += 1;
  }
  return { liveCategories, liveQuestions, awaiting };
}
