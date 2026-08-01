import { describe, it, expect } from "vitest";
import { deadFooterLinks, footerReport, FOOTER_SLUGS, type PageRow } from "@/lib/pages";

const page = (slug: string, status: "draft" | "published"): PageRow => ({
  id: 1,
  title: slug,
  slug,
  body_source: "",
  body: "",
  status,
  seo_title: "",
  seo_description: "",
  sort: 0,
  updated_at: "",
});

describe("footerReport", () => {
  it("covers every slug the storefront footer hard-codes", () => {
    expect(footerReport([]).map((r) => r.slug)).toEqual([...FOOTER_SLUGS]);
  });

  it("COUNTS A DRAFT AS A DEAD LINK, because the public API 404s one", () => {
    // The trap this exists to catch: eleven pages created and never published looks like
    // progress on the admin and is eleven broken links on the shop.
    const pages = FOOTER_SLUGS.map((s) => page(s, "draft"));

    expect(deadFooterLinks(pages)).toEqual([...FOOTER_SLUGS]);
  });

  it("reports nothing dead once every slug is published", () => {
    expect(deadFooterLinks(FOOTER_SLUGS.map((s) => page(s, "published")))).toEqual([]);
  });

  it("names exactly the ones that are missing or unpublished", () => {
    const pages = [page("privacy", "published"), page("terms", "draft")];

    const dead = deadFooterLinks(pages);

    expect(dead).toContain("terms");
    expect(dead).toContain("about");
    expect(dead).not.toContain("privacy");
  });
});
