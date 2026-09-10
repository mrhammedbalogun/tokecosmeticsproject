import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// The drawer now embeds `CountrySwitcher`, which calls `useRouter` to repaint prices
// after a change. Same stub the CountrySwitcher suite uses.
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
import { MobileNav } from "@/components/layout/MobileNav";
import type { Market } from "@/lib/country";
import { MORE_LINKS } from "@/lib/site-pages";
import { buildShopMenu } from "@/lib/shop-menu";
import type { CategoryNode } from "@/lib/catalog";

const node = (name: string, slug: string, children: CategoryNode[] = []): CategoryNode => ({
  name, slug, image: null, sort_order: 0, children,
});

// 26 flat categories, matching the live catalogue this drawer was measured against, plus
// one two-level group so the accordion is exercised.
const MENU = buildShopMenu([
  ...Array.from({ length: 26 }, (_, i) => node(`Category ${i}`, `category-${i}`)),
  { ...node("Shop By Skin Concerns", "shop-by-skin-concerns", [node("Acne", "acne")]),
    is_assignable: false },
]);

const MARKETS: Market[] = [
  {
    code: "NG", name: "Nigeria", is_default: true, is_rest_of_world: false,
    area_label: "State", currency: { code: "NGN", symbol: "₦", decimal_places: 2 },
  },
  {
    code: "GB", name: "United Kingdom", is_default: false, is_rest_of_world: false,
    area_label: "County", currency: { code: "GBP", symbol: "£", decimal_places: 2 },
  },
];

function drawer(markets: Market[] = MARKETS) {
  return <MobileNav menu={MENU} markets={markets} country="NG" />;
}

describe("MobileNav", () => {
  it("lists the More links, and lists them BEFORE the categories", () => {
    /**
     * Order is load-bearing here, not cosmetic. Measured 2026-08-16 on a 390x844
     * viewport against the live catalogue: the drawer's content is 1400px tall. Anything
     * placed after the category list starts below the fold, and the category list grows
     * with the catalogue — so "after the categories" is a position that gets worse on its
     * own, without anyone editing this file.
     */
    render(drawer());
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    const labels = screen
      .getAllByRole("link")
      .map((a) => a.textContent ?? "");
    const lastMore = Math.max(...MORE_LINKS.map((l) => labels.indexOf(l.label)));
    const firstCategory = labels.indexOf("Category 0");
    expect(lastMore).toBeGreaterThan(-1);
    expect(firstCategory).toBeGreaterThan(lastMore);
  });

  it("gives the drawer its own scroll, because the content is taller than a phone", () => {
    // Without this the panel is `fixed inset-0` + `h-full` + `overflow: visible`, which
    // CLIPS the overflow and cannot be scrolled by any gesture. Verified in a browser
    // before the fix: `scrollHeight 1400 / clientHeight 844`, and "Follow Us" stayed out
    // of the viewport even after scrolling the element programmatically.
    render(drawer());
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    expect(screen.getByRole("navigation", { name: "Mobile" }).className).toContain(
      "overflow-y-auto",
    );
  });

  it("carries the country picker, because the header no longer does below lg", () => {
    // Moved here 2026-08-16: a native <select> sizes to its longest option, so at 198px
    // it squeezed the logo to 0×0 and pushed the cart off the right edge of a 390px
    // phone. If this disappears, a phone customer has no way to change currency at all.
    render(drawer());
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    expect(screen.getByRole("combobox", { name: /country and currency/i })).toBeInTheDocument();
  });

  it("omits the picker rather than rendering an empty select when markets fail to load", () => {
    render(drawer([]));
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("keeps sub-menus collapsed until tapped", () => {
    // Expanded by default is not a style choice: sixteen destinations laid out flat is
    // the 1400px drawer the scroll test above exists because of.
    render(drawer());
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    expect(screen.queryByRole("link", { name: "Acne" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Shop By Skin Concerns/ }));
    expect(screen.getByRole("link", { name: "Acne" })).toBeInTheDocument();
    // The group's own page is reachable too — the disclosure must not swallow it.
    expect(screen.getByRole("link", { name: "All Skin Concerns" })).toHaveAttribute(
      "href", "/category/shop-by-skin-concerns",
    );
  });

  it("offers the computed Shop By Edit listings", () => {
    render(drawer());
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    const disclosure = screen.getByRole("button", { name: /Shop By Edit/ });
    fireEvent.click(disclosure);
    // Scoped to the group's own list: "Combo Deals" is DELIBERATELY in the drawer twice —
    // once as a top-level nav item (the 2026-09-02 decision that a combo is something to
    // buy, so it sits with the buying routes) and once inside this group, where Hammed's
    // menu puts it. An unscoped query would find both and fail on the ambiguity.
    const group = within(disclosure.parentElement as HTMLElement);
    for (const [label, href] of [
      ["Best Sellers", "/best-sellers"],
      ["New Arrivals", "/new-arrivals"],
      ["Promo", "/promo"],
      ["Combo Deals", "/combo"],
    ] as const) {
      expect(group.getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
  });

  it("closes when a More link is followed", () => {
    render(drawer());
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    fireEvent.click(screen.getByRole("link", { name: "Careers" }));
    expect(screen.queryByRole("navigation", { name: "Mobile" })).toBeNull();
  });
});
