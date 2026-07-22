import { describe, it, expect, beforeEach } from "vitest";
import {
  absoluteUrl, canonicalFor, pageMetadata,
  organizationJsonLd, webSiteJsonLd, breadcrumbJsonLd, productJsonLd, faqJsonLd,
} from "@/lib/seo";
import type { ProductDetail } from "@/lib/catalog";

beforeEach(() => {
  process.env.NEXT_PUBLIC_SITE_URL = "https://tokecosmetics.com";
  process.env.NEXT_PUBLIC_API_URL = "http://localhost:8000";
});

describe("absoluteUrl / canonicalFor", () => {
  it("builds absolute URLs from the site origin", () => {
    expect(absoluteUrl("/products")).toBe("https://tokecosmetics.com/products");
  });
  it("keeps page>1, strips page=1", () => {
    expect(canonicalFor("/products", { page: "2" })).toBe("https://tokecosmetics.com/products?page=2");
    expect(canonicalFor("/products", { page: "1" })).toBe("https://tokecosmetics.com/products");
  });
  it("filtered PLPs canonicalise to the bare base path (master spec)", () => {
    expect(canonicalFor("/category/face", { brand: "toke-naturals", page: "3" }))
      .toBe("https://tokecosmetics.com/category/face");
  });
});

describe("pageMetadata", () => {
  it("sets title, description, canonical, OG and twitter", () => {
    const md = pageMetadata({
      title: "Face", description: "Face care.", path: "/category/face",
      image: "http://localhost:8000/media/catalog/categories/face.png",
    });
    expect(md.title).toBe("Face");
    expect(md.alternates?.canonical).toBe("https://tokecosmetics.com/category/face");
    expect(md.openGraph?.images).toEqual(["http://localhost:8000/media/catalog/categories/face.png"]);
    expect(md.twitter).toMatchObject({ card: "summary_large_image" });
  });
  it("noindex sets robots", () => {
    const md = pageMetadata({ title: "Search", description: "d", path: "/search", noindex: true });
    expect(md.robots).toMatchObject({ index: false, follow: true });
  });
});

describe("JSON-LD builders", () => {
  it("Organization + WebSite/SearchAction", () => {
    expect(organizationJsonLd()).toMatchObject({
      "@type": "Organization", url: "https://tokecosmetics.com",
    });
    const site = webSiteJsonLd();
    expect(site.potentialAction.target).toContain("/search?q={search_term_string}");
  });

  it("BreadcrumbList positions items from 1", () => {
    const ld = breadcrumbJsonLd([
      { name: "Home", path: "/" }, { name: "Face", path: "/category/face" },
    ]);
    expect(ld.itemListElement[1]).toMatchObject({
      position: 2, name: "Face", item: "https://tokecosmetics.com/category/face",
    });
  });

  it("Product uses AggregateOffer across priced variants, money verbatim", () => {
    const product = {
      name: "Serum", slug: "serum", short_description: "Glow.",
      brand: { name: "Toke Naturals", slug: "toke-naturals", logo: null, description: "" },
      rating_avg: "4.50", rating_count: 3,
      images: [{ url: "/media/p/serum-0.png", alt: "", variant_id: null }],
      variants: [
        { id: 1, sku: "A", name: "30ml", option_values: {}, in_stock: true, low_stock: false,
          price: { amount: "18500.00", compare_at: null, currency: "NGN", tax_rate: "0.00", prices_include_tax: true } },
        { id: 2, sku: "B", name: "50ml", option_values: {}, in_stock: false, low_stock: false,
          price: { amount: "29600.00", compare_at: null, currency: "NGN", tax_rate: "0.00", prices_include_tax: true } },
      ],
    } as unknown as ProductDetail;
    const ld = productJsonLd(product, "/product/serum");
    expect(ld.offers).toMatchObject({
      "@type": "AggregateOffer", lowPrice: "18500.00", highPrice: "29600.00",
      priceCurrency: "NGN", offerCount: 2,
    });
    expect(ld.aggregateRating).toMatchObject({ ratingValue: "4.50", reviewCount: 3 });
    expect(ld.image[0]).toBe("http://localhost:8000/media/p/serum-0.png");
  });

  it("Product omits aggregateRating when no reviews and uses a single Offer for one variant", () => {
    const product = {
      name: "Balm", slug: "balm", short_description: "Calm.", brand: null,
      rating_avg: "0.00", rating_count: 0, images: [],
      variants: [{ id: 1, sku: "A", name: "60ml", option_values: {}, in_stock: true, low_stock: false,
        price: { amount: "9900.00", compare_at: null, currency: "NGN", tax_rate: "0.00", prices_include_tax: true } }],
    } as unknown as ProductDetail;
    const ld = productJsonLd(product, "/product/balm");
    expect(ld.aggregateRating).toBeUndefined();
    expect(ld.offers).toMatchObject({ "@type": "Offer", price: "9900.00",
      availability: "https://schema.org/InStock" });
  });

  it("FAQPage maps q/a pairs", () => {
    const ld = faqJsonLd([{ q: "Safe?", a: "Yes." }]);
    expect(ld.mainEntity[0]).toMatchObject({
      "@type": "Question", name: "Safe?",
      acceptedAnswer: { "@type": "Answer", text: "Yes." },
    });
  });
});
