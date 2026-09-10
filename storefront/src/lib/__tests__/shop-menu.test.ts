import { describe, expect, it } from "vitest";
import { buildShopMenu, menuHrefs, EDIT_GROUP_LABEL } from "@/lib/shop-menu";
import type { CategoryNode } from "@/lib/catalog";

const node = (
  name: string,
  slug: string,
  extra: Partial<CategoryNode> = {},
): CategoryNode => ({ name, slug, image: null, sort_order: 0, children: [], ...extra });

/** The approved menu, as the API returns it after `rebuild_shop_menu`. */
const TREE: CategoryNode[] = [
  node("Baby/Kids & Care", "baby-kids-care"),
  node("Hair Care", "hair-care"),
  node("Skin Care", "skin-care"),
  node("Facial Care", "facial-care"),
  node("Shop By Skin Concerns", "shop-by-skin-concerns", {
    is_assignable: false,
    children: [
      node("Acne", "acne"),
      node("Dry Skin", "dry-skin"),
      node("Hyperpigmentation", "hyperpigmentation"),
      node("Oily Skin", "oily-skin"),
    ],
  }),
  node("Travel Sizes", "travel-sizes"),
  node("Shop By Skin Tone", "shop-by-skin-tone", {
    is_assignable: false,
    children: [
      node("Fair Skin", "fair-skin"),
      node("Caramel Skin", "caramel-skin"),
      node("Deep Skin", "deep-skin"),
    ],
  }),
];

const labels = (tree: CategoryNode[]) =>
  buildShopMenu(tree).map((e) => (e.kind === "link" ? e.link.label : e.group.label));

describe("buildShopMenu", () => {
  it("produces the approved menu, in the approved order", () => {
    expect(labels(TREE)).toEqual([
      "Baby/Kids & Care",
      "Hair Care",
      "Skin Care",
      "Facial Care",
      "Shop By Skin Concerns",
      "Travel Sizes",
      EDIT_GROUP_LABEL,
      "Shop By Skin Tone",
    ]);
  });

  it("does not re-sort: position is the admin's to set via sort_order", () => {
    // The API already orders by (sort_order, name). Sorting again here would mean two
    // places decide position and the admin's reorder would appear not to work.
    const reversed = [...TREE].reverse();
    expect(labels(reversed).slice(0, 2)).toEqual(["Shop By Skin Tone", "Travel Sizes"]);
  });

  it("gives a group heading its own page, so the click is not swallowed", () => {
    const concerns = buildShopMenu(TREE).find(
      (e) => e.kind === "group" && e.group.label === "Shop By Skin Concerns",
    );
    expect(concerns?.kind === "group" && concerns.group.href).toBe(
      "/category/shop-by-skin-concerns",
    );
  });

  it("gives Shop By Edit no page of its own, because it has none", () => {
    const edit = buildShopMenu(TREE).find(
      (e) => e.kind === "group" && e.group.label === EDIT_GROUP_LABEL,
    );
    expect(edit?.kind === "group" && edit.group.href).toBeNull();
  });

  it("points the Shop By Edit entries at the computed listings and the combo page", () => {
    const edit = buildShopMenu(TREE).find(
      (e) => e.kind === "group" && e.group.label === EDIT_GROUP_LABEL,
    );
    const links = edit?.kind === "group" ? edit.group.links : [];
    expect(links.map((l) => [l.label, l.href])).toEqual([
      ["Best Sellers", "/best-sellers"],
      ["New Arrivals", "/new-arrivals"],
      ["Promo", "/promo"],
      ["Combo Deals", "/combo"],
      ["Travel Sizes", "/category/travel-sizes"],
    ]);
  });

  it("drops the Travel Sizes shortcut if that category is gone", () => {
    // The only entry in Shop By Edit that IS a category. Hiding it in the admin must
    // remove the shortcut, not leave a menu item pointing at a 404.
    const withoutTravel = TREE.filter((n) => n.slug !== "travel-sizes");
    const edit = buildShopMenu(withoutTravel).find(
      (e) => e.kind === "group" && e.group.label === EDIT_GROUP_LABEL,
    );
    const links = edit?.kind === "group" ? edit.group.links : [];
    expect(links.map((l) => l.href)).not.toContain("/category/travel-sizes");
    expect(links).toHaveLength(4);
  });

  it("drops a heading that has nothing under it yet", () => {
    // The state between creating "Shop By Skin Tone" and adding the first tone: no
    // product can be filed on a heading, so its page would be empty.
    const tree = [node("Shop By Skin Tone", "shop-by-skin-tone", { is_assignable: false })];
    expect(labels(tree)).toEqual([EDIT_GROUP_LABEL]);
  });

  it("keeps a childless ORDINARY category as a plain link", () => {
    expect(labels([node("Hair Care", "hair-care")])).toEqual([
      "Hair Care", EDIT_GROUP_LABEL,
    ]);
  });

  it("treats a category with no is_assignable field as assignable", () => {
    // The API caches category payloads for an hour, so a response written before the
    // field existed can still arrive. Missing must mean "shoppable", the old behaviour.
    expect(labels([node("Hair Care", "hair-care")])).toContain("Hair Care");
  });

  it("still shows Shop By Edit when the tree is empty or fails to load", () => {
    // `Header` swallows a failed category fetch to `[]`. Best Sellers, New Arrivals and
    // Promo do not depend on the tree, so losing it must not lose them too.
    expect(labels([])).toEqual([EDIT_GROUP_LABEL]);
  });

  it("places Shop By Edit last rather than dropping it from a short menu", () => {
    expect(labels([node("Hair Care", "hair-care")])).toEqual(["Hair Care", EDIT_GROUP_LABEL]);
  });
});

describe("menuHrefs", () => {
  it("lists every destination once", () => {
    const hrefs = menuHrefs(buildShopMenu(TREE));
    expect(new Set(hrefs).size).toBe(hrefs.length);
    expect(hrefs).toContain("/category/acne");
    expect(hrefs).toContain("/best-sellers");
    // Travel Sizes appears twice in the menu — as a top-level shelf and as a Shop By Edit
    // shortcut — and must be one URL, not two.
    expect(hrefs.filter((h) => h === "/category/travel-sizes")).toHaveLength(1);
  });
});
