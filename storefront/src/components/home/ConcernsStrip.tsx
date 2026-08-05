import Link from "next/link";
import type { CmsBanner } from "@/lib/cms";
import { TileMedia, bannersFor } from "@/components/home/TileMedia";
import { FadeUp } from "@/components/motion/Motion";

/** Artifact section: three joined wide tiles. CMS "Shop-by-concern tile" banners
 * replace the built-ins in order — title is the label, image/video the ground,
 * CTA URL the destination. */
const DEFAULTS = [
  { label: "Acne", href: "/products?q=acne", tone: "from-[#6b5140] to-[#2a1e16]" },
  { label: "Hyperpigmentation", href: "/products?q=brightening", tone: "from-[#5a463a] to-[#241a12]" },
  { label: "Dry Skin", href: "/products?q=hydrating", tone: "from-[#7d6a53] to-[#33281c]" },
];

export function ConcernsStrip({ banners }: { banners: CmsBanner[] }) {
  const cms = bannersFor(banners, "concern");
  const tiles = DEFAULTS.map((d, i) => ({ ...d, banner: cms[i] ?? null }));
  return (
    <section aria-label="Shop by concern" className="wrap pb-12">
      <FadeUp>
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted">
          Shop by Concern
        </p>
        <h2 className="mt-1 font-display text-3xl md:text-4xl">Start where your skin is</h2>
        <div className="mt-8 grid gap-0.5 overflow-hidden rounded-[var(--radius-card)] md:grid-cols-3">
          {tiles.map((tile) => (
            <Link
              key={tile.label}
              href={tile.banner?.cta_url || tile.href}
              className="group relative flex aspect-[16/7] items-center justify-center overflow-hidden focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <TileMedia banner={tile.banner} tone={tile.tone} sizes="(max-width: 768px) 100vw, 33vw" />
              <span aria-hidden className="absolute inset-0 bg-black/20" />
              <span className="relative border-b border-surface/60 pb-1.5 text-[13px] uppercase tracking-[0.2em] text-surface transition-colors group-hover:border-leaf group-hover:text-leaf">
                {tile.banner?.title || tile.label}
              </span>
            </Link>
          ))}
        </div>
      </FadeUp>
    </section>
  );
}
