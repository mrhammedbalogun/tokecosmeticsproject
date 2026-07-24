/** The single source of SEO truth: canonical policy, generateMetadata factory,
 * JSON-LD builders. Every page imports from here — no page hand-rolls metadata.
 * Money in JSON-LD is the API string verbatim (never recomputed). */
import type { Metadata } from "next";
import { mediaUrl } from "@/lib/media";
import type { ProductDetail } from "@/lib/catalog";

export const SITE_NAME = "Toke Cosmetics";
export const TITLE_TEMPLATE = `%s | ${SITE_NAME}`;
export const DEFAULT_DESCRIPTION =
  "Premium skincare for melanin-rich skin — natural ingredients, science-backed, shipped from Nigeria worldwide.";

export function siteUrl(): string {
  return (process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000").replace(/\/$/, "");
}
export function absoluteUrl(path: string): string {
  return `${siteUrl()}${path.startsWith("/") ? path : `/${path}`}`;
}

/** Canonical policy (docs/architecture.md § Plan-13): keep ONLY `page` (when >1);
 * any other param present → canonical is the bare base path (filtered PLP variants
 * consolidate onto the category/listing base). */
export function canonicalFor(
  path: string, searchParams: Record<string, string | undefined> = {},
): string {
  const entries = Object.entries(searchParams).filter(([, v]) => v !== undefined && v !== "");
  const nonPage = entries.filter(([k]) => k !== "page");
  if (nonPage.length > 0) return absoluteUrl(path);
  const page = Number(searchParams.page ?? "1");
  return page > 1 ? `${absoluteUrl(path)}?page=${page}` : absoluteUrl(path);
}

export interface PageMeta {
  title: string; description: string; path: string;
  searchParams?: Record<string, string | undefined>;
  image?: string | null; noindex?: boolean;
  /** Open Graph object type. Defaults to "website"; the PDP passes "product" so
   * the og:type matches the Product JSON-LD (existing callers are unchanged). */
  ogType?: "website" | "product";
}

export function pageMetadata(meta: PageMeta): Metadata {
  const canonical = canonicalFor(meta.path, meta.searchParams);
  // Next 16's typed OpenGraph union has NO `product` member (only website/article/
  // book/profile/music.*/video.*), and its `other` field emits `name=` not the
  // `property=` an OG tag needs. So for a PDP we omit openGraph.type here (Next emits
  // og:type only for a known literal) and the PDP page renders the correct
  // <meta property="og:type" content="product"> itself (React 19 hoists it to head).
  // Non-product callers keep type:"website" exactly as before.
  const isProduct = meta.ogType === "product";
  return {
    title: meta.title,
    description: meta.description,
    alternates: { canonical },
    openGraph: {
      title: meta.title, description: meta.description, url: canonical,
      siteName: SITE_NAME,
      ...(isProduct ? {} : { type: "website" as const }),
      ...(meta.image ? { images: [meta.image] } : {}),
    },
    twitter: {
      card: "summary_large_image", title: meta.title, description: meta.description,
      ...(meta.image ? { images: [meta.image] } : {}),
    },
    ...(meta.noindex ? { robots: { index: false, follow: true } } : {}),
  };
}

// ---------------- JSON-LD ----------------
/* eslint-disable @typescript-eslint/no-explicit-any */

export function organizationJsonLd(): Record<string, any> {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: SITE_NAME,
    url: siteUrl(),
    logo: absoluteUrl("/logos/toke-logo.png"),
    sameAs: [
      "https://www.instagram.com/tokecosmetics",
      "https://www.facebook.com/tokecosmetics",
      "https://www.tiktok.com/@tokecosmetics",
    ],
  };
}

export function webSiteJsonLd(): Record<string, any> {
  return {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: SITE_NAME,
    url: siteUrl(),
    potentialAction: {
      "@type": "SearchAction",
      target: `${siteUrl()}/search?q={search_term_string}`,
      "query-input": "required name=search_term_string",
    },
  };
}

export function breadcrumbJsonLd(
  crumbs: { name: string; path: string }[],
): Record<string, any> {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: crumbs.map((c, i) => ({
      "@type": "ListItem", position: i + 1, name: c.name, item: absoluteUrl(c.path),
    })),
  };
}

const AVAILABILITY = {
  in: "https://schema.org/InStock",
  out: "https://schema.org/OutOfStock",
};

export function productJsonLd(product: ProductDetail, path: string): Record<string, any> {
  const url = absoluteUrl(path);
  const priced = product.variants.filter((v) => v.price !== null);
  const anyInStock = priced.some((v) => v.in_stock);
  const currency = priced[0]?.price?.currency;

  let offers: Record<string, any> | undefined;
  if (priced.length === 1) {
    offers = {
      "@type": "Offer", url, price: priced[0].price!.amount, priceCurrency: currency,
      availability: priced[0].in_stock ? AVAILABILITY.in : AVAILABILITY.out,
    };
  } else if (priced.length > 1) {
    // Compare as numbers to pick low/high, but EMIT the original API strings.
    const sorted = [...priced].sort((a, b) => Number(a.price!.amount) - Number(b.price!.amount));
    offers = {
      "@type": "AggregateOffer", url,
      lowPrice: sorted[0].price!.amount,
      highPrice: sorted[sorted.length - 1].price!.amount,
      priceCurrency: currency, offerCount: priced.length,
      availability: anyInStock ? AVAILABILITY.in : AVAILABILITY.out,
    };
  }
  // priceValidUntil deliberately omitted — the API does not expose sale windows
  // (Plan-13 flagged risk); the property is optional.

  return {
    "@context": "https://schema.org",
    "@type": "Product",
    name: product.name,
    url,
    description: product.short_description || product.seo_description || undefined,
    image: product.images.map((i) => mediaUrl(i.url)).filter(Boolean),
    ...(product.brand ? { brand: { "@type": "Brand", name: product.brand.name } } : {}),
    sku: product.variants[0]?.sku,
    ...(offers ? { offers } : {}),
    ...(product.rating_count > 0
      ? { aggregateRating: {
          "@type": "AggregateRating",
          ratingValue: product.rating_avg, reviewCount: product.rating_count,
        } }
      : {}),
  };
}

export function faqJsonLd(faqs: { q: string; a: string }[]): Record<string, any> {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faqs.map((f) => ({
      "@type": "Question", name: f.q,
      acceptedAnswer: { "@type": "Answer", text: f.a },
    })),
  };
}
