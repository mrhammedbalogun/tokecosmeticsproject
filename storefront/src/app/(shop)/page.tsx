import type { Metadata } from "next";
import { cookies } from "next/headers";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { getProducts } from "@/lib/catalog";
import { getHomepage, rowCollection } from "@/lib/cms";
import { pageMetadata, organizationJsonLd, webSiteJsonLd, DEFAULT_DESCRIPTION } from "@/lib/seo";
import { JsonLd } from "@/components/seo/JsonLd";
import { HeroSlider } from "@/components/home/HeroSlider";
import { ShopByCategory } from "@/components/home/ShopByCategory";
import { ConcernsStrip } from "@/components/home/ConcernsStrip";
import { FeatureSplit } from "@/components/home/FeatureSplit";
import { ProductRow } from "@/components/home/ProductRow";
import { GenderSection } from "@/components/home/GenderSection";
import { TikTokSection } from "@/components/home/TikTokSection";
import { TrioSection } from "@/components/home/TrioSection";
import { Journal } from "@/components/home/Journal";
import { GoogleReviews } from "@/components/home/GoogleReviews";
import { bannerFor } from "@/components/home/TileMedia";

export const metadata: Metadata = pageMetadata({
  title: "Toke Cosmetics — Premium Skincare for Melanin-Rich Skin",
  description: DEFAULT_DESCRIPTION,
  path: "/",
});

export default async function HomePage() {
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  // Plan-19c: a scheduled, country-targeted hero from the CMS, or the Plan-13 fixture.
  const homepage = await getHomepage(country);
  const collection = (slug: string) =>
    getProducts({ collection: slug }, country).then((p) => p.results).catch(() => []);
  // The two product rows read admin-chosen collections (Home Content screen), falling
  // back to the slugs this page always used.
  const lovedSlug = rowCollection(homepage, "loved", "best-sellers");
  const naturalSlug = rowCollection(homepage, "natural", "new-arrivals");
  const [bestSellers, newArrivals, men, women, babies] = await Promise.all([
    collection(lovedSlug),
    getProducts({ collection: naturalSlug, ordering: "newest" }, country)
      .then((p) => p.results)
      .catch(() => []),
    // The three feature sections read admin-curated collections and HIDE when a
    // collection is empty or missing — creating "men"/"women"/"babies" in admin is
    // what turns each section on.
    collection("men"),
    collection("women"),
    collection("babies"),
  ]);
  return (
    <>
      <JsonLd data={organizationJsonLd()} />
      <JsonLd data={webSiteJsonLd()} />
      {/* The approved artifact, section for section, top to bottom. */}
      <HeroSlider banners={homepage?.banners ?? []} />
      <ShopByCategory banners={homepage?.banners ?? []} />
      <ConcernsStrip banners={homepage?.banners ?? []} />
      <FeatureSplit banners={homepage?.banners ?? []} />
      <ProductRow
        title="Loved by thousands"
        eyebrow="Best Sellers"
        products={bestSellers.slice(0, 8)}
        href={`/products?collection=${lovedSlug}`}
        carousel
        compact
      />
      <GenderSection
        eyebrow="New Formulas"
        title="New for Men"
        tagline="Made for men's skin"
        href="/products?collection=men"
        products={men}
        banner={bannerFor(homepage?.banners ?? [], "men")}
        tone="from-[#2f2a26] to-[#0f0d0b]"
      />
      <GenderSection
        eyebrow="Radiance Rituals"
        title="For Women"
        tagline="Glow that starts with care"
        href="/products?collection=women"
        products={women}
        banner={bannerFor(homepage?.banners ?? [], "women")}
        flip
        tone="from-[#7a5c42] to-[#2b1f16]"
      />
      <GenderSection
        eyebrow="Gentle by Design"
        title="For Babies"
        tagline="Soft care for the softest skin"
        href="/products?collection=babies"
        products={babies}
        banner={bannerFor(homepage?.banners ?? [], "babies")}
        tone="from-[#2c4a33] to-[#0e2015]"
      />
      <ProductRow
        title="Natural Products"
        eyebrow="New Arrivals"
        products={newArrivals.slice(0, 8)}
        href={
          naturalSlug === "new-arrivals"
            ? "/products?ordering=newest"
            : `/products?collection=${naturalSlug}`
        }
        compact
      />
      <TikTokSection banner={bannerFor(homepage?.banners ?? [], "tiktok")} products={bestSellers.slice(4, 8).length ? bestSellers.slice(4, 8) : newArrivals.slice(0, 4)} />
      <TrioSection banners={homepage?.banners ?? []} />
      <Journal />
      <GoogleReviews reviews={homepage?.reviews} />
    </>
  );
}
