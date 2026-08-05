import Link from "next/link";
import type { CmsBanner } from "@/lib/cms";
import { TileMedia, bannersFor } from "@/components/home/TileMedia";
import { FadeUp } from "@/components/motion/Motion";

/** Artifact section: the Kids / Men's Essentials / Family trio. CMS "Collections
 * trio tile" banners replace the built-ins in order — title, tagline, CTA text and
 * URL, image/video. */
const DEFAULTS = [
  { title: "Kids' Collection", sub: "Made comfortable for growing skin.", href: "/products?collection=babies", tone: "from-[#42502e] to-[#181e10]" },
  { title: "Men's Essentials", sub: "Built for strength, made to refresh.", href: "/products?collection=men", tone: "from-[#33291f] to-[#100d09]" },
  { title: "Family", sub: "Together in care, together in glow.", href: "/products", tone: "from-[#4c5a35] to-[#1a2113]" },
];

export function TrioSection({ banners }: { banners: CmsBanner[] }) {
  const cms = bannersFor(banners, "trio");
  const tiles = DEFAULTS.map((d, i) => ({ ...d, banner: cms[i] ?? null }));
  return (
    <section aria-label="Collections" className="wrap py-8">
      <FadeUp>
        <div className="grid gap-4 md:grid-cols-3">
          {tiles.map((tile) => (
            <div
              key={tile.title}
              className="relative flex aspect-[3/4] items-end overflow-hidden rounded-[var(--radius-card)]"
            >
              <TileMedia banner={tile.banner} tone={tile.tone} sizes="(max-width: 768px) 100vw, 33vw" />
              <span aria-hidden className="absolute inset-0 bg-gradient-to-t from-black/50 via-transparent to-transparent" />
              <div className="relative p-7">
                <h3 className="font-display text-2xl text-surface">{tile.banner?.title || tile.title}</h3>
                <p className="mt-1.5 text-sm text-surface/80">{tile.banner?.tagline || tile.sub}</p>
                <Link
                  href={tile.banner?.cta_url || tile.href}
                  className="mt-4 inline-block rounded-full border border-surface/70 px-6 py-2.5 text-xs font-medium uppercase tracking-[0.08em] text-surface transition hover:bg-surface/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface"
                >
                  {tile.banner?.cta_text || "Explore"}
                </Link>
              </div>
            </div>
          ))}
        </div>
      </FadeUp>
    </section>
  );
}
