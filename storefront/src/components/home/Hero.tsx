import Image from "next/image";
import Link from "next/link";
import { HERO } from "@/lib/home-content";
import type { CmsBanner } from "@/lib/cms";

/** Section 3: full-width cinematic hero. LCP-critical — the image is `priority`
 * and the only motion is a CSS-keyframe slow zoom (motion-safe, zero JS), so the
 * hero costs nothing on the Lighthouse budget. The left-weighted scrim keeps the
 * white serif headline AA-legible over the placeholder gradient art. */
export function Hero({ banner }: { banner?: CmsBanner | null } = {}) {
  // A CMS hero overrides the fixture field by field, so a marketer can change the
  // headline without also having to supply artwork. Anything they leave blank keeps the
  // Plan-13 value — the alternative is a half-filled banner blanking the LCP image.
  const content = {
    eyebrow: banner?.subtitle || HERO.eyebrow,
    headline: banner?.title || HERO.headline,
    sub: HERO.sub,
    image: banner?.image || HERO.image,
    ctaText: banner?.cta_text || "",
    ctaHref: banner?.cta_url || "",
  };
  return (
    <section className="relative flex min-h-[78vh] items-center overflow-hidden">
      <Image
        src={content.image}
        alt=""
        fill
        priority
        sizes="100vw"
        className="object-cover motion-safe:animate-[heroZoom_18s_ease-out_forwards]"
      />
      <div className="absolute inset-0 bg-gradient-to-r from-black/45 via-black/15 to-transparent" />
      <div className="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-black/25 to-transparent" />
      <div className="relative mx-auto w-full max-w-7xl px-4 py-24 md:py-32">
        <p className="mb-5 flex items-center gap-3 text-xs font-medium uppercase tracking-[0.22em] text-surface/85">
          <span className="h-px w-8 bg-gold" aria-hidden />
          {content.eyebrow}
        </p>
        <h1 className="max-w-2xl font-display text-5xl leading-[1.05] text-surface md:text-7xl">
          {content.headline}
        </h1>
        <p className="mt-6 max-w-xl text-lg leading-relaxed text-surface/90">{content.sub}</p>
        <div className="mt-9 flex flex-wrap gap-4">
          {HERO.ctas.map((cta) => (
            <Link
              key={cta.label}
              href={cta.href}
              className={
                cta.primary
                  ? "rounded-full bg-surface px-8 py-3.5 font-medium text-foreground shadow-sm transition hover:bg-background hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface"
                  : "rounded-full border border-surface/70 px-8 py-3.5 font-medium text-surface transition hover:bg-surface/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface"
              }
            >
              {cta.label}
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
