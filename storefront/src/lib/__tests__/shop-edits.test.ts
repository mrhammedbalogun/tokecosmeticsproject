import { describe, expect, it } from "vitest";
import { SHOP_EDITS, shopEdit } from "@/lib/shop-edits";
import { buildProductQuery } from "@/lib/catalog";
import { buildShopMenu, EDIT_GROUP_LABEL } from "@/lib/shop-menu";
import type { CategoryNode } from "@/lib/catalog";

describe("the Shop By Edit listings", () => {
  it("asks the API for the right thing", () => {
    // The whole difference between the three pages is these params, so they are worth
    // pinning: a typo here is a page that silently lists the entire catalogue.
    expect(buildProductQuery(SHOP_EDITS["best-sellers"].params)).toBe(
      "ordering=best_selling",
    );
    expect(buildProductQuery(SHOP_EDITS["new-arrivals"].params)).toBe("ordering=newest");
    expect(buildProductQuery(SHOP_EDITS.promo.params)).toBe("on_sale=1");
  });

  it("locks the ordering only where the ORDER is the page", () => {
    // Promo is a SET, not a sequence — sorting it by price is still Promo, so the control
    // stays. Sorting Best Sellers by price is not a best-seller page, so it goes.
    expect(SHOP_EDITS["best-sellers"].fixedOrdering).toBe("best_selling");
    expect(SHOP_EDITS["new-arrivals"].fixedOrdering).toBe("newest");
    expect(SHOP_EDITS.promo.fixedOrdering).toBeUndefined();
  });

  it("gives every listing an empty state, because two of them can legitimately be empty", () => {
    // Production has ZERO reduced prices today, so /promo ships empty and the empty state
    // is the page until somebody sets a was-price.
    for (const edit of Object.values(SHOP_EDITS)) {
      expect(edit.empty.length).toBeGreaterThan(0);
      expect(edit.metaDescription.length).toBeGreaterThan(0);
    }
  });

  it("has a page behind every Shop By Edit menu link that claims one", () => {
    // The menu and the routes are separate files; this is what stops them drifting into a
    // nav item that 404s. /combo and /category/* are covered by their own routes.
    const tree: CategoryNode[] = [
      { name: "Travel Sizes", slug: "travel-sizes", image: null, sort_order: 0, children: [] },
    ];
    const group = buildShopMenu(tree).find(
      (e) => e.kind === "group" && e.group.label === EDIT_GROUP_LABEL,
    );
    const links = group?.kind === "group" ? group.group.links : [];
    for (const link of links) {
      if (link.href.startsWith("/category/") || link.href === "/combo") continue;
      expect(shopEdit(link.href.slice(1))).toBeDefined();
    }
  });

  it("returns undefined for a slug that is not an edit", () => {
    expect(shopEdit("not-an-edit")).toBeUndefined();
  });
});
