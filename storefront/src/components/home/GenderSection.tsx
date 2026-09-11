import Link from "next/link";
import type { ProductCard as ProductCardData } from "@/lib/catalog";
import type { CmsBanner } from "@/lib/cms";
import { ProductCard } from "@/components/product/ProductCard";
import { TileMedia, isArtwork } from "@/components/home/TileMedia";
import { FadeUp } from "@/components/motion/Motion";

/** The Men / Women / Babies feature block (approved 2026-08-04): a tall editorial
 * tile beside a 2×2 grid of compact product cards. `flip` mirrors the layout so
 * the three sections alternate sides down the page instead of repeating.
 *
 * Renders nothing when the collection is empty — a heading over a blank grid
 * would advertise a gap. The tile's artwork comes from the CMS homepage section
 * config when set (image or video URL), else the brand-gradient fallback.
 */
export function GenderSection({
  eyebrow,
  title,
  tagline,
  href,
  products,
  flip = false,
  banner = null,
  tone = "from-[#2f2a26] to-[#0f0d0b]",
}: {
  eyebrow: string;
  title: string;
  tagline: string;
  href: string;
  products: ProductCardData[];
  flip?: boolean;
  /** CMS override (placement men/women/babies): subtitle=eyebrow, title, tagline,
   * CTA URL and image/video all beat the built-ins when set. */
  banner?: CmsBanner | null;
  tone?: string;
}) {
  if (products.length === 0) return null;
  return (
    <section aria-label={title} className="wrap py-8">
      <FadeUp>
        <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
          {(() => {
            const heading = banner?.title || title;
            const to = banner?.cta_url || href;
            const box = `relative flex min-h-[420px] items-center justify-center overflow-hidden rounded-[var(--radius-card)] text-center lg:min-h-[520px] ${
              flip ? "lg:order-2" : ""
            }`;
            const media = <TileMedia banner={banner} tone={tone} sizes="(max-width: 1024px) 100vw, 55vw" />;
            // A finished piece already says all of this in the picture; the shop adds
            // nothing and the whole panel is the link. The heading stays for the
            // document outline — a section whose only words are painted on is invisible
            // to a screen reader otherwise.
            if (isArtwork(banner)) {
              return (
                <Link
                  href={to}
                  aria-label={heading}
                  className={`${box} focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent`}
                >
                  {media}
                  <h2 className="sr-only">{heading}</h2>
                </Link>
              );
            }
            return (
              <div className={box}>
                {media}
                <div aria-hidden className="absolute inset-0 bg-black/25" />
                <div className="relative px-8">
                  <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-surface/80">
                    {banner?.subtitle || eyebrow}
                  </p>
                  <h2 className="mt-2 font-display text-4xl italic text-surface md:text-5xl">
                    {heading}
                  </h2>
                  <p className="mt-3 text-sm text-surface/85">{banner?.tagline || tagline}</p>
                  <Link
                    href={to}
                    className="mt-7 inline-block rounded-full border border-surface/70 px-7 py-3 text-sm font-medium text-surface transition hover:bg-surface/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface"
                  >
                    {banner?.cta_text || "Shop now"}
                  </Link>
                </div>
              </div>
            );
          })()}
          <div className="grid grid-cols-2 gap-4">
            {products.slice(0, 4).map((p) => (
              <ProductCard key={p.slug} product={p} compact />
            ))}
          </div>
        </div>
      </FadeUp>
    </section>
  );
}
