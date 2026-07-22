import { cookies } from "next/headers";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { getCategoryTree } from "@/lib/catalog";
import { Hero } from "@/components/home/Hero";
import { FeaturedCategories } from "@/components/home/FeaturedCategories";
import { SkinConcerns } from "@/components/home/SkinConcerns";
import { BrandStory } from "@/components/home/BrandStory";

export default async function HomePage() {
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const categories = await getCategoryTree(country).catch(() => []);
  return (
    <>
      <Hero />
      <FeaturedCategories categories={categories} />
      <SkinConcerns />
      <BrandStory />
      {/* Sections 7-14 land in Task 7 */}
    </>
  );
}
