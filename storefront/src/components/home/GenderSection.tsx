import Link from "next/link";
import Image from "next/image";
import type { ProductCard as ProductCardData } from "@/lib/catalog";
import { ProductCard } from "@/components/product/ProductCard";
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
  image,
  video,
  tone = "from-[#2f2a26] to-[#0f0d0b]",
}: {
  eyebrow: string;
  title: string;
  tagline: string;
  href: string;
  products: ProductCardData[];
  flip?: boolean;
  image?: string | null;
  video?: string | null;
  tone?: string;
}) {
  if (products.length === 0) return null;
  return (
    <section aria-label={title} className="mx-auto max-w-7xl px-4 py-8">
      <FadeUp>
        <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
          <div
            className={`relative flex min-h-[420px] items-center justify-center overflow-hidden rounded-[var(--radius-card)] text-center lg:min-h-[520px] ${
              flip ? "lg:order-2" : ""
            }`}
          >
            {video ? (
              <video
                className="absolute inset-0 h-full w-full object-cover"
                src={video}
                poster={image ?? undefined}
                autoPlay
                muted
                loop
                playsInline
              />
            ) : image ? (
              <Image src={image} alt="" fill sizes="(max-width: 1024px) 100vw, 55vw" className="object-cover" />
            ) : (
              <div aria-hidden className={`absolute inset-0 bg-gradient-to-br ${tone}`} />
            )}
            <div aria-hidden className="absolute inset-0 bg-black/25" />
            <div className="relative px-8">
              <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-surface/80">
                {eyebrow}
              </p>
              <h2 className="mt-2 font-display text-4xl italic text-surface md:text-5xl">{title}</h2>
              <p className="mt-3 text-sm text-surface/85">{tagline}</p>
              <Link
                href={href}
                className="mt-7 inline-block rounded-full border border-surface/70 px-7 py-3 text-sm font-medium text-surface transition hover:bg-surface/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface"
              >
                Shop now
              </Link>
            </div>
          </div>
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
