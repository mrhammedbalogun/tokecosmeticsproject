/**
 * Grouping and the live-count, which is the number the FAQ screen exists to show.
 *
 * "4 categories, 20 questions" is not what a customer sees: the storefront hides a
 * category with nothing published in it, and the seeded policy questions arrive
 * unpublished on purpose. The screen has to say what is actually live.
 */
import { describe, expect, it } from "vitest";
import { groupByCategory, publicSummary, type FaqCategoryRow, type FaqItemRow } from "@/lib/faq";

function cat(id: number, over: Partial<FaqCategoryRow> = {}): FaqCategoryRow {
  return {
    id, name: `Cat ${id}`, slug: `cat-${id}`, blurb: "", sort: id,
    is_active: true, item_count: 0, ...over,
  };
}
function item(id: number, category: number, over: Partial<FaqItemRow> = {}): FaqItemRow {
  return {
    id, category, category_name: "", question: `q${id}`, answer_source: "<p>a</p>",
    answer: "<p>a</p>", sort: id, is_published: true, ...over,
  };
}

describe("groupByCategory", () => {
  it("orders categories and their questions the way the shop will", () => {
    const groups = groupByCategory(
      [cat(2, { sort: 2 }), cat(1, { sort: 1 })],
      [item(20, 2, { sort: 2 }), item(10, 2, { sort: 1 }), item(30, 1)],
    );
    expect(groups.map((g) => g.category.id)).toEqual([1, 2]);
    expect(groups[1].items.map((i) => i.id)).toEqual([10, 20]);
  });

  it("keeps an empty category, because the editor still has to see it", () => {
    const groups = groupByCategory([cat(1)], []);
    expect(groups).toHaveLength(1);
    expect(groups[0].items).toEqual([]);
  });
});

describe("publicSummary", () => {
  it("counts only what a customer can reach", () => {
    const groups = groupByCategory(
      [cat(1), cat(2), cat(3, { is_active: false })],
      [
        item(1, 1), item(2, 1, { is_published: false }),
        item(3, 2, { is_published: false }),   // whole category still unanswered
        item(4, 3),                            // published, but category switched off
      ],
    );

    expect(publicSummary(groups)).toEqual({
      liveCategories: 1,   // only cat 1 has something published AND is active
      liveQuestions: 1,
      awaiting: 2,         // the two unpublished, wherever they sit
    });
  });

  it("reports the seeded state honestly: categories exist, nothing is live", () => {
    const groups = groupByCategory(
      [cat(1), cat(2)],
      [item(1, 1, { is_published: false }), item(2, 2, { is_published: false })],
    );
    expect(publicSummary(groups)).toEqual({ liveCategories: 0, liveQuestions: 0, awaiting: 2 });
  });
});
