/** Shapes for the CMS pages admin. No fetching — that is the page component.
 *
 * THE ELEVEN SLUGS BELOW ARE A CONTRACT WITH THE STOREFRONT. `Footer.tsx` hard-codes them,
 * so a slug that is missing or unpublished is a dead link on a live shop. The admin lists
 * them explicitly rather than leaving an editor to guess which pages the site expects —
 * that reconciliation is Plan-19a's whole point, and it cannot be done from memory.
 *
 * If the footer changes, this list changes with it. There is no endpoint that reports a
 * storefront component's hard-coded links, and inventing one to avoid eleven literals
 * would be the larger sin (the same call `products/page.tsx` made about currencies).
 */
export const FOOTER_SLUGS = [
  "about",
  "blog",
  "community",
  "wholesale",
  "affiliates",
  "shipping",
  "returns",
  "contact",
  "faqs",
  "privacy",
  "terms",
] as const;

export interface PageRow {
  id: number;
  title: string;
  slug: string;
  body_source: string;
  body: string;
  status: "draft" | "published";
  seo_title: string;
  seo_description: string;
  sort: number;
  updated_at: string;
}

export type FooterState = "published" | "draft" | "missing";

/** What the storefront footer would do with each of its links, right now. */
export function footerReport(pages: PageRow[]): { slug: string; state: FooterState }[] {
  const bySlug = new Map(pages.map((p) => [p.slug, p]));
  return FOOTER_SLUGS.map((slug) => {
    const page = bySlug.get(slug);
    if (!page) return { slug, state: "missing" as const };
    return {
      slug,
      state: page.status === "published" ? ("published" as const) : ("draft" as const),
    };
  });
}

/** Footer links that would 404 today — missing pages AND drafts, because the public API
 *  answers 404 for a draft too. Eleven pages created and never published looks like
 *  progress on the admin and is eleven broken links on the shop. */
export function deadFooterLinks(pages: PageRow[]): string[] {
  return footerReport(pages)
    .filter((row) => row.state !== "published")
    .map((row) => row.slug);
}
