import Link from "next/link";
import type { ProductCard as ProductCardData } from "@/lib/catalog";
import type { CmsBanner } from "@/lib/cms";
import { ProductCard } from "@/components/product/ProductCard";
import { TileMedia } from "@/components/home/TileMedia";
import { FadeUp } from "@/components/motion/Motion";

/** Artifact section: a 2×2 product grid beside the "TikTok Made Me Try It" promo
 * tile. Hides with no products, like every data-driven section. */
export function TikTokSection({
  products,
  banner = null,
}: {
  products: ProductCardData[];
  /** CMS override (placement "tiktok"): title, tagline, CTA and image/video. */
  banner?: CmsBanner | null;
}) {
  if (products.length === 0) return null;
  return (
    <section aria-label="TikTok favourites" className="mx-auto max-w-7xl px-4 py-8">
      <FadeUp>
        <div className="grid gap-4 lg:grid-cols-[1fr_1.1fr]">
          <div className="grid grid-cols-2 gap-4">
            {products.slice(0, 4).map((p) => (
              <ProductCard key={p.slug} product={p} compact />
            ))}
          </div>
          <div className="relative flex min-h-[420px] items-end overflow-hidden rounded-[var(--radius-card)]">
            <TileMedia banner={banner} tone="from-[#3a5238] to-[#141d13]" sizes="(max-width: 1024px) 100vw, 55vw" />
            <span aria-hidden className="absolute inset-0 bg-gradient-to-t from-black/45 via-transparent to-transparent" />
            <div className="relative p-10">
              <h2 className="font-display text-3xl italic text-surface md:text-4xl">
                {banner?.title || "TikTok Made Me Try It"}
              </h2>
              <p className="mt-2 text-sm text-surface/85">
                {banner?.tagline || "The community favourites, as seen on your feed."}
              </p>
              <Link
                href={banner?.cta_url || "/products?collection=best-sellers"}
                className="mt-6 inline-block rounded-full border border-surface/70 px-7 py-3 text-sm font-medium text-surface transition hover:bg-surface/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface"
              >
                {banner?.cta_text || "Shop Now"}
              </Link>
            </div>
          </div>
        </div>
      </FadeUp>
    </section>
  );
}
