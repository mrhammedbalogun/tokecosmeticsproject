import Link from "next/link";
import type { ProductCard as ProductCardData } from "@/lib/catalog";
import { ProductCard } from "@/components/product/ProductCard";
import { FadeUp } from "@/components/motion/Motion";

/** Artifact section: a 2×2 product grid beside the "TikTok Made Me Try It" promo
 * tile. Hides with no products, like every data-driven section. */
export function TikTokSection({ products }: { products: ProductCardData[] }) {
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
          <div className="relative flex min-h-[420px] items-end overflow-hidden rounded-[var(--radius-card)] bg-gradient-to-br from-[#3a5238] to-[#141d13]">
            <div className="p-10">
              <h2 className="font-display text-3xl italic text-surface md:text-4xl">
                TikTok Made Me Try It
              </h2>
              <p className="mt-2 text-sm text-surface/85">
                The community favourites, as seen on your feed.
              </p>
              <Link
                href="/products?collection=best-sellers"
                className="mt-6 inline-block rounded-full border border-surface/70 px-7 py-3 text-sm font-medium text-surface transition hover:bg-surface/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface"
              >
                Shop Now
              </Link>
            </div>
          </div>
        </div>
      </FadeUp>
    </section>
  );
}
