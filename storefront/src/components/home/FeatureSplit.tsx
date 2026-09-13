import Link from "next/link";
import type { CmsBanner } from "@/lib/cms";
import { TileMedia, bannerFor, isArtwork } from "@/components/home/TileMedia";
import { FadeUp } from "@/components/motion/Motion";

/** Artifact section: the Glow Set feature beside the tokè × natural stack. Each of
 * the three tiles is CMS-overridable ("Glow Set feature", "tokè × natural tile",
 * "Toke Naturals tile"): title, tagline, CTA and image/video. */
export function FeatureSplit({ banners }: { banners: CmsBanner[] }) {
  const feature = bannerFor(banners, "feature");
  const nature = bannerFor(banners, "feature_nature");
  const collection = bannerFor(banners, "feature_collection");
  return (
    <section aria-label={feature?.title || "The Glow Set"} className="wrap pb-12">
      <FadeUp>
        <div className="grid gap-4 lg:grid-cols-[1.25fr_1fr]">
          <GlowSet banner={feature} />
          <div className="grid gap-4">
            <SmallTile
              banner={nature}
              tone="from-[#1f4d33] to-[#0b1f13]"
              eyebrow="tokè × natural"
              heading="Grown from nature, proven by science"
            />
            <SmallTile
              banner={collection}
              tone="from-[#8a6a3d] to-[#3a2b16]"
              eyebrow="Collection"
              heading="Toke Naturals"
              href={collection?.cta_url || "/products?q=natural"}
            />
          </div>
        </div>
      </FadeUp>
    </section>
  );
}

/** The big left-hand tile. */
function GlowSet({ banner }: { banner?: CmsBanner | null }) {
  const heading = banner?.title || "The Glow Set";
  const href = banner?.cta_url || "/products?collection=best-sellers";
  const box = "relative flex min-h-[430px] items-end overflow-hidden rounded-[var(--radius-card)]";
  const media = (
    <TileMedia banner={banner} tone="from-[#31502f] to-[#12200f]" sizes="(max-width: 1024px) 100vw, 55vw" />
  );
  if (isArtwork(banner)) {
    return (
      <Link
        href={href}
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
      <span aria-hidden className="absolute inset-0 bg-gradient-to-t from-black/45 via-transparent to-transparent" />
      <div className="relative p-10">
        <h2 className="font-display text-4xl text-surface md:text-5xl">{heading}</h2>
        <p className="mt-3 max-w-sm text-sm leading-relaxed text-surface/85">
          {banner?.tagline ||
            "Brightening oil, daily facial wash and repair cream — the routine our community swears by."}
        </p>
        <Link
          href={href}
          className="mt-6 inline-block rounded-full bg-surface px-7 py-3 text-sm font-medium text-foreground transition hover:bg-background focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface"
        >
          {banner?.cta_text || "Shop the Set"}
        </Link>
      </div>
    </div>
  );
}

/**
 * One of the two stacked tiles beside the Glow Set. `href` is what separates them: the
 * tokè × natural tile is mood, not a destination, so it has none.
 *
 * These have no height of their own — `TileMedia` is absolutely positioned, so their
 * copy block IS the box. On `lg` the outer grid stretches this column to the Glow Set's
 * height and the two rows share it; BELOW `lg` nothing imposes a height, so a finished
 * piece — which has no copy block — would collapse to nothing. In artwork mode the tile
 * therefore carries the placement's own 2:1 shape below `lg`, and drops back to
 * `aspect-auto` at `lg` where the stretched row already gives it one.
 *
 * `lg:aspect-auto` is load-bearing, not tidiness: measured in Chromium, a ratio left on
 * at `lg` BEATS the stretch rather than yielding to it — the tiles became 309px each at
 * 1440 and pushed the whole section from 430px to 634px, dragging the Glow Set beside
 * them taller with it. Turning it off at `lg` measures 207px, exactly the overlay
 * layout. Like every tile, this one still fills and crops; "artwork" here promises only
 * that the shop writes nothing over it.
 */
function SmallTile({
  banner,
  tone,
  eyebrow,
  heading,
  href,
}: {
  banner?: CmsBanner | null;
  tone: string;
  eyebrow: string;
  heading: string;
  href?: string;
}) {
  const title = banner?.title || heading;
  const box = "relative flex items-end overflow-hidden rounded-[var(--radius-card)]";
  const focus = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
  const media = (
    <TileMedia banner={banner} tone={tone} sizes="(max-width: 1024px) 100vw, 45vw" />
  );
  if (isArtwork(banner)) {
    const art = `${box} aspect-[2/1] lg:aspect-auto`;
    // The heading survives as `sr-only`: on the linked tile it is the link's only
    // accessible name, since the image renders `alt=""`.
    if (!href) {
      return (
        <div className={art}>
          {media}
          <h3 className="sr-only">{title}</h3>
        </div>
      );
    }
    return (
      <Link href={href} aria-label={title} className={`${art} ${focus}`}>
        {media}
        <h3 className="sr-only">{title}</h3>
      </Link>
    );
  }
  const body = (
    <>
      {media}
      <div className="relative p-6">
        <p className="text-[11px] uppercase tracking-[0.22em] text-surface/70">
          {banner?.subtitle || eyebrow}
        </p>
        <h3 className="mt-1 font-display text-xl text-surface">{title}</h3>
      </div>
    </>
  );
  if (!href) return <div className={box}>{body}</div>;
  return (
    <Link href={href} className={`${box} ${focus}`}>
      {body}
    </Link>
  );
}
