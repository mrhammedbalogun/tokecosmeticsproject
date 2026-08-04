import type { Metadata } from "next";
import { cookies } from "next/headers";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { getCategoryTree, getProducts } from "@/lib/catalog";
import { getHomepage } from "@/lib/cms";
import { pageMetadata, organizationJsonLd, webSiteJsonLd, DEFAULT_DESCRIPTION } from "@/lib/seo";
import { JsonLd } from "@/components/seo/JsonLd";
import { HeroSlider } from "@/components/home/HeroSlider";
import { GenderSection } from "@/components/home/GenderSection";
import { GoogleReviews } from "@/components/home/GoogleReviews";
import { FeaturedCategories } from "@/components/home/FeaturedCategories";
import { SkinConcerns } from "@/components/home/SkinConcerns";
import { BrandStory } from "@/components/home/BrandStory";
import { ProductRow } from "@/components/home/ProductRow";
import { CollectionBanner } from "@/components/home/CollectionBanner";
import { WhyChoose } from "@/components/home/WhyChoose";
import { CommunityGrid } from "@/components/home/CommunityGrid";
import { EducationTeasers } from "@/components/home/EducationTeasers";
import { NewsletterCta } from "@/components/home/NewsletterCta";

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
  const [categories, bestSellers, newArrivals, men, women, babies] = await Promise.all([
    getCategoryTree(country).catch(() => []),
    collection("best-sellers"),
    getProducts({ collection: "new-arrivals", ordering: "newest" }, country)
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
      <HeroSlider banners={homepage?.banners ?? []} />
      <FeaturedCategories categories={categories} />
      <SkinConcerns />
      <BrandStory />
      <ProductRow
        title="Loved by thousands"
        eyebrow="Best Sellers"
        products={bestSellers.slice(0, 8)}
        href="/products?collection=best-sellers"
        carousel
        compact
      />
      <GenderSection
        eyebrow="New Formulas"
        title="New for Men"
        tagline="Made for men's skin"
        href="/products?collection=men"
        products={men}
        tone="from-[#2f2a26] to-[#0f0d0b]"
      />
      <GenderSection
        eyebrow="Radiance Rituals"
        title="For Women"
        tagline="Glow that starts with care"
        href="/products?collection=women"
        products={women}
        flip
        tone="from-[#7a5c42] to-[#2b1f16]"
      />
      <GenderSection
        eyebrow="Gentle by Design"
        title="For Babies"
        tagline="Soft care for the softest skin"
        href="/products?collection=babies"
        products={babies}
        tone="from-[#2c4a33] to-[#0e2015]"
      />
      <ProductRow
        title="Natural Products"
        eyebrow="New Arrivals"
        products={newArrivals.slice(0, 8)}
        href="/products?ordering=newest"
        compact
      />
      <CollectionBanner />
      <WhyChoose />
      <CommunityGrid />
      <EducationTeasers />
      <GoogleReviews reviews={homepage?.reviews} />
      <NewsletterCta />
    </>
  );
}
