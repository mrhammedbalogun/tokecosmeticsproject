import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MobileNav } from "@/components/layout/MobileNav";
import { MORE_LINKS } from "@/lib/site-pages";

const CATEGORIES = Array.from({ length: 26 }, (_, i) => ({
  name: `Category ${i}`,
  slug: `category-${i}`,
}));

describe("MobileNav", () => {
  it("lists the More links, and lists them BEFORE the categories", () => {
    /**
     * Order is load-bearing here, not cosmetic. Measured 2026-08-16 on a 390x844
     * viewport against the live catalogue: the drawer's content is 1400px tall. Anything
     * placed after the category list starts below the fold, and the category list grows
     * with the catalogue — so "after the categories" is a position that gets worse on its
     * own, without anyone editing this file.
     */
    render(<MobileNav categories={CATEGORIES} />);
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
    render(<MobileNav categories={CATEGORIES} />);
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    expect(screen.getByRole("navigation", { name: "Mobile" }).className).toContain(
      "overflow-y-auto",
    );
  });

  it("closes when a More link is followed", () => {
    render(<MobileNav categories={CATEGORIES} />);
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    fireEvent.click(screen.getByRole("link", { name: "Careers" }));
    expect(screen.queryByRole("navigation", { name: "Mobile" })).toBeNull();
  });
});
