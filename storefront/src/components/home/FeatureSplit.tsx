import Link from "next/link";
import type { CmsBanner } from "@/lib/cms";
import { TileMedia, bannerFor } from "@/components/home/TileMedia";
import { FadeUp } from "@/components/motion/Motion";

/** Artifact section: the Glow Set feature beside the tokè × natural stack. Each of
 * the three tiles is CMS-overridable ("Glow Set feature", "tokè × natural tile",
 * "Toke Naturals tile"): title, tagline, CTA and image/video. */
export function FeatureSplit({ banners }: { banners: CmsBanner[] }) {
  const feature = bannerFor(banners, "feature");
  const nature = bannerFor(banners, "feature_nature");
  const collection = bannerFor(banners, "feature_collection");
  return (
    <section aria-label={feature?.title || "The Glow Set"} className="mx-auto max-w-7xl px-4 pb-12">
      <FadeUp>
        <div className="grid gap-4 lg:grid-cols-[1.25fr_1fr]">
          <div className="relative flex min-h-[430px] items-end overflow-hidden rounded-[var(--radius-card)]">
            <TileMedia banner={feature} tone="from-[#31502f] to-[#12200f]" sizes="(max-width: 1024px) 100vw, 55vw" />
            <span aria-hidden className="absolute inset-0 bg-gradient-to-t from-black/45 via-transparent to-transparent" />
            <div className="relative p-10">
              <h2 className="font-display text-4xl text-surface md:text-5xl">
                {feature?.title || "The Glow Set"}
              </h2>
              <p className="mt-3 max-w-sm text-sm leading-relaxed text-surface/85">
                {feature?.tagline ||
                  "Brightening oil, daily facial wash and repair cream — the routine our community swears by."}
              </p>
              <Link
                href={feature?.cta_url || "/products?collection=best-sellers"}
                className="mt-6 inline-block rounded-full bg-surface px-7 py-3 text-sm font-medium text-foreground transition hover:bg-background focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface"
              >
                {feature?.cta_text || "Shop the Set"}
              </Link>
            </div>
          </div>
          <div className="grid gap-4">
            <div className="relative flex items-end overflow-hidden rounded-[var(--radius-card)]">
              <TileMedia banner={nature} tone="from-[#1f4d33] to-[#0b1f13]" sizes="(max-width: 1024px) 100vw, 45vw" />
              <div className="relative p-6">
                <p className="text-[11px] uppercase tracking-[0.22em] text-surface/70">
                  {nature?.subtitle || "tokè × natural"}
                </p>
                <h3 className="mt-1 font-display text-xl text-surface">
                  {nature?.title || "Grown from nature, proven by science"}
                </h3>
              </div>
            </div>
            <Link
              href={collection?.cta_url || "/products?q=natural"}
              className="relative flex items-end overflow-hidden rounded-[var(--radius-card)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <TileMedia banner={collection} tone="from-[#8a6a3d] to-[#3a2b16]" sizes="(max-width: 1024px) 100vw, 45vw" />
              <div className="relative p-6">
                <p className="text-[11px] uppercase tracking-[0.22em] text-surface/70">
                  {collection?.subtitle || "Collection"}
                </p>
                <h3 className="mt-1 font-display text-xl text-surface">
                  {collection?.title || "Toke Naturals"}
                </h3>
              </div>
            </Link>
          </div>
        </div>
      </FadeUp>
    </section>
  );
}
