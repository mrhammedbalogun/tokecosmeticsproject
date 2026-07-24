import Image from "next/image";
import Link from "next/link";
import { BRAND_STORY } from "@/lib/home-content";
import { FadeUp } from "@/components/motion/Motion";

/** Section 6: brand story — split editorial. Offset image pair on the left, copy
 * with the four brand pillars on the right (natural ingredients · science-backed ·
 * made for melanin-rich skin · trusted worldwide, per the design brief). The gold
 * tick marks are the "seasoning" luxury accent. */
export function BrandStory() {
  return (
    <section aria-labelledby="story-h" className="mx-auto max-w-7xl px-4 py-24">
      <div className="grid items-center gap-10 md:grid-cols-2 md:gap-16">
        <div className="grid grid-cols-2 gap-4">
          {BRAND_STORY.images.map((src, i) => (
            <FadeUp key={src} delay={i * 0.1}>
              <Image
                src={src}
                alt=""
                width={900}
                height={1100}
                className={`rounded-[var(--radius-card)] object-cover shadow-sm ${i === 1 ? "mt-10" : ""}`}
              />
            </FadeUp>
          ))}
        </div>
        <FadeUp>
          <div className="max-w-lg">
            <p className="flex items-center gap-3 text-xs font-medium uppercase tracking-[0.22em] text-accent">
              <span className="h-px w-8 bg-gold" aria-hidden />
              {BRAND_STORY.eyebrow}
            </p>
            <h2 id="story-h" className="mt-4 font-display text-3xl md:text-4xl">
              {BRAND_STORY.title}
            </h2>
            {BRAND_STORY.paragraphs.map((p) => (
              <p key={p.slice(0, 20)} className="mt-5 leading-relaxed text-muted">
                {p}
              </p>
            ))}
            <ul className="mt-8 grid grid-cols-2 gap-x-6 gap-y-3">
              {BRAND_STORY.pillars.map((pillar) => (
                <li key={pillar} className="flex items-center gap-2.5 text-sm font-medium">
                  <span
                    aria-hidden
                    className="grid h-5 w-5 place-items-center rounded-full bg-accent/10 text-xs text-gold"
                  >
                    ✓
                  </span>
                  {pillar}
                </li>
              ))}
            </ul>
            <Link
              href={BRAND_STORY.cta.href}
              className="mt-9 inline-block border-b border-accent pb-0.5 font-medium text-accent transition-colors hover:border-accent-strong hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              {BRAND_STORY.cta.label} →
            </Link>
          </div>
        </FadeUp>
      </div>
    </section>
  );
}
