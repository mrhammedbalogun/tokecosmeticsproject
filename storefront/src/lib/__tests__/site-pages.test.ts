import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { MORE_LINKS, MORE_MENU_LABEL } from "@/lib/site-pages";

const SHOP = join(process.cwd(), "src", "app", "(shop)");

/**
 * The `More` menu is a list of links in one file and a set of route files in another
 * directory, and NOTHING AT RUNTIME CONNECTS THEM. Adding a label to `MORE_LINKS` and
 * forgetting the folder ships a header link straight to the 404 page, on every page of
 * the shop, and it looks completely fine in review. That is exactly the failure mode the
 * footer already shipped with — its `/page/*` links pointed at CMS rows that were never
 * created, so five of them 404 in production today.
 *
 * These tests are the connection. They read the filesystem rather than mocking it.
 */
describe("the More menu's links all resolve to real routes", () => {
  it.each(MORE_LINKS.map((l) => [l.label, l.href] as const))(
    "%s -> %s has a page.tsx",
    (_label, href) => {
      expect(existsSync(join(SHOP, href.replace(/^\//, ""), "page.tsx"))).toBe(true);
    },
  );

  it("has no duplicate hrefs or labels", () => {
    // A duplicate href would also make React's `key={item.href}` collide.
    expect(new Set(MORE_LINKS.map((l) => l.href)).size).toBe(MORE_LINKS.length);
    expect(new Set(MORE_LINKS.map((l) => l.label)).size).toBe(MORE_LINKS.length);
  });

  it("uses only root-relative paths", () => {
    // An absolute URL here would send a customer off-site from the primary nav, and
    // `sitemap.ts` would emit `https://tokecosmetics.com/https://…`.
    for (const link of MORE_LINKS) {
      expect(link.href.startsWith("/")).toBe(true);
      expect(link.href).not.toMatch(/^\/\//);
    }
  });

  it("keeps the trigger label short enough for the nav bar", () => {
    // The trigger sits in a five-item nav next to a search box; a sentence there wraps
    // the header on a laptop.
    expect(MORE_MENU_LABEL.length).toBeLessThanOrEqual(12);
  });
});

describe("the top-level nav items still exist too", () => {
  // Blog moved INTO `More` on 2026-08-16 and Skin Quiz did not. If a later edit moves
  // Skin Quiz as well, this test does not fail — but the one above starts covering it,
  // so the route stays guarded either way.
  it.each(["skin-quiz", "products"])("/%s has a page.tsx", (slug) => {
    expect(existsSync(join(SHOP, slug, "page.tsx"))).toBe(true);
  });
});
