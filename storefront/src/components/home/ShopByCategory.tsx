import Link from "next/link";
import type { CmsBanner } from "@/lib/cms";
import { TileMedia, bannersFor } from "@/components/home/TileMedia";
import { FadeUp } from "@/components/motion/Motion";

/** Artifact section: four tall photo tiles with a centred pill label. Each tile is
 * a CMS banner (placement "Shop-by-category tile"): its title is the pill label,
 * its image/video the artwork, its CTA URL the destination. CMS tiles replace the
 * built-in four IN ORDER; missing ones keep the built-in label, link and tone. */
const DEFAULTS = [
  { label: "Best Sellers", href: "/products?collection=best-sellers", tone: "from-[#7a5c42] to-[#2e2119]" },
  { label: "Skin", href: "/products", tone: "from-[#4b342a] to-[#1c120d]" },
  { label: "Hair", href: "/products?q=hair", tone: "from-[#33291f] to-[#120d09]" },
  { label: "Babies", href: "/products?collection=babies", tone: "from-[#2c3b2b] to-[#101a10]" },
];

export function ShopByCategory({ banners }: { banners: CmsBanner[] }) {
  const cms = bannersFor(banners, "category");
  const tiles = DEFAULTS.map((d, i) => ({ ...d, banner: cms[i] ?? null }));
  return (
    <section aria-label="Shop by category" className="wrap py-12">
      <FadeUp>
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted">
          Shop by Category
        </p>
        <h2 className="mt-1 font-display text-3xl md:text-4xl">Made for every one of you</h2>
        <div className="mt-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
          {tiles.map((tile) => (
            <Link
              key={tile.label}
              href={tile.banner?.cta_url || tile.href}
              className="group relative flex aspect-[3/4] items-center justify-center overflow-hidden rounded-[var(--radius-card)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <TileMedia banner={tile.banner} tone={tile.tone} sizes="(max-width: 1024px) 50vw, 25vw" />
              <span className="relative rounded-full border border-surface/60 bg-black/35 px-6 py-2.5 text-xs uppercase tracking-[0.14em] text-surface backdrop-blur-sm transition-colors group-hover:border-accent group-hover:bg-accent">
                {tile.banner?.title || tile.label}
              </span>
            </Link>
          ))}
        </div>
      </FadeUp>
    </section>
  );
}
