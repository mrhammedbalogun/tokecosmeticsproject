"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import type { CmsBanner } from "@/lib/cms";
import { HERO } from "@/lib/home-content";
import { mediaUrl } from "@/lib/media";

/** The hero SLIDER (landing redesign, approved 2026-08-04). Full-bleed, square
 * corners, the Plan-13 hero's min-h-[78vh]. Slides are CMS hero banners in sort
 * order; each is an image banner or — when `video_url` is set — an autoplaying
 * muted looping video with the image as poster. No media-type is ever labelled
 * for the customer (Hammed's ruling).
 *
 * Chrome mirrors the production site's slider, upgraded: numbered title tabs
 * (01/02/03) that are clickable, an autoplay progress bar on the active tab,
 * and arrows. Autoplay advances every 6s and pauses under reduced-motion (no
 * timer, no video autoplay). With ONE slide all chrome hides and this renders
 * exactly like the old static hero — the CMS deciding one banner must not build
 * a carousel around it.
 *
 * The first slide's image keeps `priority`: it is the LCP whatever the CMS says.
 */
interface Slide {
  key: string;
  eyebrow: string;
  headline: string;
  sub: string;
  image: string | null;
  /** A different crop for phones, not a resize — rendered as its own <Image>. */
  mobileImage: string | null;
  video: string;
  ctaText: string;
  ctaHref: string;
}

function slidesFrom(banners: CmsBanner[]): Slide[] {
  const heroes = banners
    .filter((b) => b.placement === "hero")
    .sort((a, b) => a.sort - b.sort)
    .map((b) => ({
      key: `cms-${b.id}`,
      eyebrow: b.subtitle,
      headline: b.title,
      sub: "",
      image: mediaUrl(b.image),
      mobileImage: mediaUrl(b.mobile_image),
      video: b.video_url,
      ctaText: b.cta_text,
      ctaHref: b.cta_url,
    }));
  if (heroes.length) return heroes;
  // Empty CMS: the Plan-13 fixture hero, as ever — the front door never blanks.
  return [
    {
      key: "fixture",
      eyebrow: HERO.eyebrow,
      headline: HERO.headline,
      sub: HERO.sub,
      image: HERO.image,
      mobileImage: null,
      video: "",
      ctaText: "",
      ctaHref: "",
    },
  ];
}

const INTERVAL_MS = 6000;

export function HeroSlider({ banners }: { banners: CmsBanner[] }) {
  const slides = slidesFrom(banners);
  const [current, setCurrent] = useState(0);
  const [reduced, setReduced] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const many = slides.length > 1;

  useEffect(() => {
    setReduced(window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }, []);

  const show = useCallback(
    (index: number) => setCurrent((index + slides.length) % slides.length),
    [slides.length],
  );

  useEffect(() => {
    if (!many || reduced) return;
    timer.current = setTimeout(() => show(current + 1), INTERVAL_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [current, many, reduced, show]);

  return (
    <section className="relative min-h-[78vh] overflow-hidden" aria-label="Highlights">
      {slides.map((slide, i) => (
        <div
          key={slide.key}
          className={`${i === current ? "opacity-100" : "pointer-events-none opacity-0"} absolute inset-0 transition-opacity duration-700 motion-reduce:transition-none`}
          aria-hidden={i !== current}
        >
          {slide.video && !reduced ? (
            <video
              className="absolute inset-0 h-full w-full object-cover"
              src={slide.video}
              poster={slide.image ?? undefined}
              autoPlay
              muted
              loop
              playsInline
            />
          ) : slide.image && slide.mobileImage ? (
            <>
              <Image
                src={slide.mobileImage}
                alt=""
                fill
                priority={i === 0}
                sizes="100vw"
                className="object-cover md:hidden"
              />
              <Image
                src={slide.image}
                alt=""
                fill
                priority={i === 0}
                sizes="100vw"
                className="hidden object-cover md:block"
              />
            </>
          ) : slide.image ? (
            <Image
              src={slide.image}
              alt=""
              fill
              priority={i === 0}
              sizes="100vw"
              className="object-cover"
            />
          ) : (
            <div className="absolute inset-0 bg-gradient-to-br from-accent-strong to-foreground" />
          )}
          <div className="absolute inset-0 bg-gradient-to-r from-black/45 via-black/15 to-transparent" />
          <div className="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-black/30 to-transparent" />
          <div className="relative flex min-h-[78vh] items-center">
            <div className="wrap py-24">
              {slide.eyebrow && (
                <p className="mb-5 flex items-center gap-3 text-xs font-medium uppercase tracking-[0.22em] text-surface/85">
                  <span className="h-px w-8 bg-gold" aria-hidden />
                  {slide.eyebrow}
                </p>
              )}
              <h1 className="max-w-2xl font-display text-5xl leading-[1.05] text-surface md:text-7xl">
                {slide.headline}
              </h1>
              {slide.sub && (
                <p className="mt-6 max-w-xl text-lg leading-relaxed text-surface/90">{slide.sub}</p>
              )}
              {slide.ctaText && slide.ctaHref && (
                <div className="mt-9">
                  <Link
                    href={slide.ctaHref}
                    className="rounded-full bg-surface px-8 py-3.5 font-medium text-foreground shadow-sm transition hover:bg-background hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface"
                  >
                    {slide.ctaText}
                  </Link>
                </div>
              )}
            </div>
          </div>
        </div>
      ))}

      {many && (
        <>
          <button
            type="button"
            onClick={() => show(current - 1)}
            aria-label="Previous slide"
            className="absolute left-4 top-1/2 z-10 grid h-11 w-11 -translate-y-1/2 place-items-center rounded-full border border-surface/50 bg-black/25 text-surface transition hover:bg-black/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface"
          >
            ‹
          </button>
          <button
            type="button"
            onClick={() => show(current + 1)}
            aria-label="Next slide"
            className="absolute right-4 top-1/2 z-10 grid h-11 w-11 -translate-y-1/2 place-items-center rounded-full border border-surface/50 bg-black/25 text-surface transition hover:bg-black/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface"
          >
            ›
          </button>
          <div className="wrap absolute inset-x-0 bottom-6 z-10 flex gap-7">
            {slides.map((slide, i) => (
              <button
                key={slide.key}
                type="button"
                onClick={() => show(i)}
                aria-current={i === current ? "true" : undefined}
                className={`relative flex-1 border-t-2 pt-2.5 text-left text-[11px] uppercase tracking-[0.12em] transition-colors ${
                  i === current ? "border-leaf text-surface" : "border-surface/25 text-surface/65 hover:text-surface"
                }`}
              >
                {i === current && !reduced && (
                  <span
                    aria-hidden
                    className="absolute -top-0.5 left-0 h-0.5 animate-[heroTab_6s_linear_forwards] bg-leaf"
                  />
                )}
                {String(i + 1).padStart(2, "0")}
                <span className="mt-0.5 block truncate text-xs normal-case tracking-normal text-surface font-medium">
                  {slide.headline}
                </span>
              </button>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
