import type { MetadataRoute } from "next";
import { flattenCategories, getCategoryTree, getProducts } from "@/lib/catalog";
import { getPages } from "@/lib/cms";
import { MORE_LINKS } from "@/lib/site-pages";
import { absoluteUrl } from "@/lib/seo";
import { DEFAULT_COUNTRY } from "@/lib/country";

/** Single sitemap (catalog << 50k URLs; shard with generateSitemaps() only if the
 * catalog ever approaches ~10k). Uses the NG default market — URLs are country-
 * agnostic (one URL set; currency is an in-session choice, see architecture.md).
 * CMS pages (/page/*) joined in Plan-19a; only PUBLISHED ones are listed, because the
 * API only serves those. The header's `More` pages (/about-us, /careers, …) are code
 * routes and join from `lib/site-pages.ts` — the same list the nav renders from.
 * /search and /cart and /checkout are deliberately absent. */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const entries: MetadataRoute.Sitemap = [
    { url: absoluteUrl("/"), changeFrequency: "daily", priority: 1 },
    { url: absoluteUrl("/products"), changeFrequency: "daily", priority: 0.9 },
  ];

  // The `More` menu's pages (2026-08-16). Static code routes, so unlike the CMS block
  // below there is no fetch to fail and no published/draft distinction — if the link is
  // in the header it is in the sitemap, by construction.
  for (const link of MORE_LINKS) {
    entries.push({
      url: absoluteUrl(link.href),
      changeFrequency: "monthly",
      priority: link.priority,
    });
  }

  // Policy and editorial pages. A failure costs the sitemap those URLs, never the whole
  // file — the same posture the catalogue fetches below take.
  for (const page of await getPages().catch(() => [])) {
    entries.push({
      url: absoluteUrl(`/page/${page.slug}`),
      lastModified: page.updated_at ? new Date(page.updated_at) : undefined,
      changeFrequency: "monthly", priority: 0.4,
    });
  }

  const tree = await getCategoryTree(DEFAULT_COUNTRY).catch(() => []);
  for (const cat of flattenCategories(tree)) {
    entries.push({
      url: absoluteUrl(`/category/${cat.slug}`),
      changeFrequency: "daily", priority: 0.8,
    });
  }

  // Page through /products/ (24/page). Hard cap of 100 pages (=2400 products) as a
  // runaway guard; revisit when the WP migration (Plan-21) lands the full catalog.
  let page = 1;
  for (;;) {
    const batch = await getProducts({ page, ordering: "newest" }, DEFAULT_COUNTRY)
      .catch(() => null);
    if (!batch) break;
    for (const p of batch.results) {
      entries.push({
        url: absoluteUrl(`/product/${p.slug}`),
        changeFrequency: "weekly", priority: 0.7,
      });
    }
    if (!batch.next || page >= 100) break;
    page += 1;
  }
  return entries;
}
