import { describe, it, expect } from "vitest";
import { buildSeoPreview, TITLE_SUFFIX, truncate } from "@/lib/seo-preview";

const input = (overrides: Partial<Parameters<typeof buildSeoPreview>[0]> = {}) => ({
  seoTitle: "",
  seoDescription: "",
  name: "Carrot Shea Butter",
  shortDescription: "Daily hydration, all-day softness.",
  slug: "carrot-shea-butter",
  siteUrl: "https://tokecosmetics.com",
  ...overrides,
});

describe("buildSeoPreview", () => {
  it("appends the site-wide title suffix", () => {
    // storefront/src/app/layout.tsx:21 — `template: "%s | Toke Cosmetics"` applies to every
    // page title. Omitting it under-reports the rendered length by 17 characters, which
    // matters precisely when somebody is trimming a title to fit.
    expect(buildSeoPreview(input({ seoTitle: "Shea Butter" })).title).toBe(
      `Shea Butter${TITLE_SUFFIX}`,
    );
  });

  it("falls back to the product name exactly as the PDP does", () => {
    // storefront/src/app/(shop)/product/[slug]/page.tsx:39
    const preview = buildSeoPreview(input({ seoTitle: "" }));

    expect(preview.title).toBe(`Carrot Shea Butter${TITLE_SUFFIX}`);
    expect(preview.titleIsFallback).toBe(true);
  });

  it("treats a whitespace-only title as empty", () => {
    expect(buildSeoPreview(input({ seoTitle: "   " })).titleIsFallback).toBe(true);
  });

  it("falls back to the short description exactly as the PDP does", () => {
    // storefront/src/app/(shop)/product/[slug]/page.tsx:40
    const preview = buildSeoPreview(input({ seoDescription: "" }));

    expect(preview.description).toBe("Daily hydration, all-day softness.");
    expect(preview.descriptionIsFallback).toBe(true);
    expect(preview.descriptionIsEmpty).toBe(false);
  });

  it("reports an empty description when there is no fallback either", () => {
    // Not an error — the page still renders. But the search engine writes its own, which
    // is how a product ends up described by its cookie banner.
    const preview = buildSeoPreview(input({ seoDescription: "", shortDescription: "" }));

    expect(preview.descriptionIsEmpty).toBe(true);
  });

  it("builds the PDP url with the SINGULAR product segment", () => {
    // `/product/<slug>`, not `/products/<slug>` — the plural is the listing page.
    expect(buildSeoPreview(input()).url).toBe(
      "https://tokecosmetics.com/product/carrot-shea-butter",
    );
  });

  it("does not double the slash when the site url has a trailing one", () => {
    expect(buildSeoPreview(input({ siteUrl: "https://tokecosmetics.com/" })).url).toBe(
      "https://tokecosmetics.com/product/carrot-shea-butter",
    );
  });

  it("prefers the explicit fields over both fallbacks", () => {
    const preview = buildSeoPreview(
      input({ seoTitle: "Best Shea Butter in Nigeria", seoDescription: "Buy online." }),
    );

    expect(preview.title).toBe(`Best Shea Butter in Nigeria${TITLE_SUFFIX}`);
    expect(preview.description).toBe("Buy online.");
    expect(preview.titleIsFallback).toBe(false);
    expect(preview.descriptionIsFallback).toBe(false);
  });
});

describe("truncate", () => {
  it("leaves text that fits alone", () => {
    expect(truncate("short", 60)).toBe("short");
  });

  it("cuts at the limit and marks the cut", () => {
    expect(truncate("abcdef", 3)).toBe("abc…");
  });

  it("does not leave a dangling space before the ellipsis", () => {
    expect(truncate("ab cdef", 3)).toBe("ab…");
  });
});
