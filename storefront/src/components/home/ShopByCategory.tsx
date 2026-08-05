import Link from "next/link";
import Image from "next/image";
import type { CmsBanner } from "@/lib/cms";
import { mediaUrl } from "@/lib/media";
import { FadeUp } from "@/components/motion/Motion";

/** Artifact section: four tall photo tiles with a centred pill label. Artwork
 * comes from CMS category-placement banners matched by title; a tile without one
 * shows its brand-gradient tone, so the section never waits on uploads. */
const TILES = [
  { label: "Best Sellers", href: "/products?collection=best-sellers", tone: "from-[#7a5c42] to-[#2e2119]" },
  { label: "Skin", href: "/products", tone: "from-[#4b342a] to-[#1c120d]" },
  { label: "Hair", href: "/products?q=hair", tone: "from-[#33291f] to-[#120d09]" },
  { label: "Babies", href: "/products?collection=babies", tone: "from-[#2c3b2b] to-[#101a10]" },
];

export function ShopByCategory({ banners }: { banners: CmsBanner[] }) {
  const art = new Map(
    banners
      .filter((b) => b.placement === "category")
      .map((b) => [b.title.toLowerCase(), b]),
  );
  return (
    <section aria-label="Shop by category" className="mx-auto max-w-7xl px-4 py-12">
      <FadeUp>
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted">
          Shop by Category
        </p>
        <h2 className="mt-1 font-display text-3xl md:text-4xl">Made for every one of you</h2>
        <div className="mt-8 grid grid-cols-2 gap-4 lg:grid-cols-4">
          {TILES.map((tile) => {
            const banner = art.get(tile.label.toLowerCase());
            const img = mediaUrl(banner?.image ?? null);
            return (
              <Link
                key={tile.label}
                href={banner?.cta_url || tile.href}
                className="group relative flex aspect-[3/4] items-center justify-center overflow-hidden rounded-[var(--radius-card)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                {img ? (
                  <Image
                    src={img}
                    alt=""
                    fill
                    sizes="(max-width: 1024px) 50vw, 25vw"
                    className="object-cover transition-transform duration-700 ease-out group-hover:scale-[1.04]"
                  />
                ) : (
                  <div aria-hidden className={`absolute inset-0 bg-gradient-to-br ${tile.tone}`} />
                )}
                <span className="relative rounded-full border border-surface/60 bg-black/35 px-6 py-2.5 text-xs uppercase tracking-[0.14em] text-surface backdrop-blur-sm transition-colors group-hover:border-accent group-hover:bg-accent">
                  {tile.label}
                </span>
              </Link>
            );
          })}
        </div>
      </FadeUp>
    </section>
  );
}
