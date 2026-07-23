import type { Metadata } from "next";
import { cookies } from "next/headers";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { getCategoryTree, getProducts } from "@/lib/catalog";
import { pageMetadata, organizationJsonLd, webSiteJsonLd, DEFAULT_DESCRIPTION } from "@/lib/seo";
import { JsonLd } from "@/components/seo/JsonLd";
import { Hero } from "@/components/home/Hero";
import { FeaturedCategories } from "@/components/home/FeaturedCategories";
import { SkinConcerns } from "@/components/home/SkinConcerns";
import { BrandStory } from "@/components/home/BrandStory";
import { ProductRow } from "@/components/home/ProductRow";
import { CollectionBanner } from "@/components/home/CollectionBanner";
import { WhyChoose } from "@/components/home/WhyChoose";
import { Testimonials } from "@/components/home/Testimonials";
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
  const [categories, bestSellers, newArrivals] = await Promise.all([
    getCategoryTree(country).catch(() => []),
    getProducts({ collection: "best-sellers" }, country).then((p) => p.results).catch(() => []),
    getProducts({ collection: "new-arrivals", ordering: "newest" }, country)
      .then((p) => p.results)
      .catch(() => []),
  ]);
  return (
    <>
      <JsonLd data={organizationJsonLd()} />
      <JsonLd data={webSiteJsonLd()} />
      <Hero />
      <FeaturedCategories categories={categories} />
      <SkinConcerns />
      <BrandStory />
      <ProductRow
        title="Best sellers"
        products={bestSellers}
        href="/products?collection=best-sellers"
        carousel
      />
      <CollectionBanner />
      <ProductRow title="New arrivals" products={newArrivals.slice(0, 8)} href="/products?ordering=newest" />
      <WhyChoose />
      <Testimonials />
      <CommunityGrid />
      <EducationTeasers />
      <NewsletterCta />
    </>
  );
}
