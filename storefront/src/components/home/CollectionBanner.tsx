import Image from "next/image";
import Link from "next/link";
import { FEATURED_COLLECTION } from "@/lib/home-content";

/** Section 8: featured collection banner ("Glow Naturally" — D3 content). Full-bleed
 * editorial promo linking into the collection PLP. A dark scrim keeps the surface-
 * white type AA-legible over the generated art; the calm image zoom on hover is the
 * design vocabulary (CSS-only, neutralised under prefers-reduced-motion by the
 * globals.css catch-all). alt="" — the copy in the overlay carries the meaning. */
export function CollectionBanner() {
  const c = FEATURED_COLLECTION;
  return (
    <section aria-label={c.title} className="mx-auto max-w-7xl px-4 py-8">
      <Link
        href={`/products?collection=${c.slug}`}
        className="group relative block overflow-hidden rounded-[var(--radius-card)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <Image
          src={c.image}
          alt=""
          width={1800}
          height={700}
          className="h-[340px] w-full object-cover transition-transform duration-700 ease-out group-hover:scale-[1.03] md:h-[420px]"
        />
        <div className="absolute inset-0 flex flex-col items-start justify-center bg-black/30 p-8 md:p-16">
          <h2 className="max-w-lg font-display text-4xl text-surface md:text-5xl">{c.title}</h2>
          <p className="mt-3 max-w-md text-surface/90">{c.sub}</p>
          <span className="mt-6 rounded-full bg-surface px-7 py-3 font-medium text-foreground transition-colors group-hover:bg-beige">
            Shop the edit
          </span>
        </div>
      </Link>
    </section>
  );
}
