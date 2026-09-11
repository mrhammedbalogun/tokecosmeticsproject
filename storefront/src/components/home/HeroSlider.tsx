"use client";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import Image from "next/image";
import Link from "next/link";
import { ClickToPlayVideo } from "@/components/home/ClickToPlayVideo";
import type { CmsBanner } from "@/lib/cms";
import { HERO } from "@/lib/home-content";
import { mediaUrl } from "@/lib/media";

/** The hero SLIDER (landing redesign, approved 2026-08-04). Full-bleed, square
 * corners. Slides are CMS hero banners in sort order; each is an image banner or —
 * when `video_url` is set — a video whose `video_mode` decides playback: "loop"
 * autoplays muted with the image as poster, "click" shows the poster with a play
 * button and fetches nothing until pressed. No media-type is ever labelled for the
 * customer (Hammed's ruling).
 *
 * ── THE BOX IS 16:9, NOT A SLICE OF THE VIEWPORT (2026-09-10) ───────────────────────
 *
 * It used to be `min-h-[78vh]`, which meant the hero's SHAPE was whatever the visitor's
 * window happened to be — 2.28:1 on a 1080p laptop, 0.59:1 on a phone — while every
 * image inside it was `object-cover`. Cover crops whatever does not fit, so the artwork
 * was silently trimmed by a different amount on every screen: on a 1920×1080 laptop the
 * Back-to-School banner lost ~100px off the top (its Toke logo) and ~100px off the
 * bottom (its "Shop Now" button); on a phone it lost two thirds of its width.
 *
 * The height now comes from the ARTWORK's ratio instead: 16:9 is the shape the admin's
 * own hero guide has always asked for ("Image 1920×1080", admin/src/lib/banners.ts), and
 * four of the five live banners are exactly that, so they now fill the box with nothing
 * cropped at all. `min-h-[24rem]` is a floor for narrow phones, where a true 16:9 strip
 * (219px on a 390px screen) would leave no room for a slide's headline; it stops binding
 * above ~683px wide. Do NOT add a `max-h`: a max-height on an aspect-ratio box does not
 * letterbox, it just cancels the ratio, and the cropping comes straight back.
 *
 * ── TWO SPECIES OF BANNER, `image_mode` DECIDES WHICH ───────────────────────────────
 *
 * "overlay" (the default, and everything before 2026-09-10) is a PHOTO shot with an
 * empty third for the site to write into: it is cropped to fill, darkened by scrims, and
 * carries the CMS eyebrow/headline/CTA on top. "artwork" is a FINISHED piece that
 * already has its own logo, headline, body copy and button painted into the pixels — so
 * it is shown WHOLE (`object-contain`, never cropped), gets no scrims and no site text,
 * and the whole image becomes the link. Its headline stays in the DOM as `sr-only`,
 * because this h1 is the only one on the homepage and screen readers cannot read pixels.
 *
 * Autoplay advances every 6s and pauses under reduced-motion (no timer, no video
 * autoplay). With ONE slide all chrome hides and this renders exactly like the old
 * static hero — the CMS deciding one banner must not build a carousel around it.
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
  /** "loop" autoplays muted; "click" waits for the visitor and shows controls. */
  videoMode: "loop" | "click";
  /** true = a finished piece: show it whole and add no text of our own. */
  artwork: boolean;
  ctaText: string;
  ctaHref: string;
}

function slidesFrom(banners: CmsBanner[]): Slide[] {
  const heroes = banners
    .filter((b) => b.placement === "hero")
    .sort((a, b) => a.sort - b.sort)
    .map((b) => {
      const image = mediaUrl(b.image);
      return {
        key: `cms-${b.id}`,
        eyebrow: b.subtitle,
        headline: b.title,
        sub: "",
        image,
        mobileImage: mediaUrl(b.mobile_image),
        video: b.video_url,
        videoMode: b.video_mode,
        // A backend that predates the field sends nothing; that must read as "overlay",
        // which is what every banner made before 2026-09-10 is.
        //
        // AND artwork mode needs artwork. "Show the picture, write nothing" with no
        // picture attached is a blank gradient with no words on it — a slide that says
        // nothing at all. Without media the slide falls back to speaking for itself.
        artwork: b.image_mode === "artwork" && Boolean(image || b.video_url),
        ctaText: b.cta_text,
        ctaHref: b.cta_url,
      };
    });
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
      videoMode: "loop",
      artwork: false,
      ctaText: "",
      ctaHref: "",
    },
  ];
}

const INTERVAL_MS = 6000;

const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";
const subscribeReduced = (onChange: () => void) => {
  const media = window.matchMedia(REDUCED_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
};

export function HeroSlider({ banners }: { banners: CmsBanner[] }) {
  const slides = slidesFrom(banners);
  const [current, setCurrent] = useState(0);
  // The media query is external state, so it is read as such — the server snapshot says
  // "reduced" so SSR/first paint never starts a video or a timer the user asked not to
  // have; the client corrects at hydration and follows live OS changes.
  const reduced = useSyncExternalStore(
    subscribeReduced,
    () => window.matchMedia(REDUCED_QUERY).matches,
    () => true,
  );
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const many = slides.length > 1;

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
    <section
      // `w-full` is NOT decoration. The shop layout makes this a flex child, so its
      // width is shrink-to-fit — and an `aspect-ratio` box whose width is indefinite
      // solves the ratio the OTHER way round, taking its width from `min-h-[24rem]`.
      // Without this the hero came out 683px wide on a 390px phone and the whole page
      // scrolled sideways. Pin the width; let the ratio decide only the height.
      className="relative aspect-[16/9] w-full min-h-[24rem] overflow-hidden"
      aria-label="Highlights"
    >
      {slides.map((slide, i) => {
        // Contain NEVER crops, whatever shape the box ends up: it is the only fit that
        // can promise a finished piece of artwork survives a window we do not control.
        const fit: "object-cover" | "object-contain" = slide.artwork
          ? "object-contain"
          : "object-cover";
        const media = (
          <>
            {/* The box is 16:9 and so is almost every asset, so these bars are hairlines
              * — but an off-ratio artwork (or a very wide window) would otherwise sit on
              * bare white. A blurred, over-scaled copy of the same file fills them; it
              * is the same URL and srcset, so it costs no extra download. */}
            {slide.artwork && slide.mobileImage && (
              <Image
                src={slide.mobileImage}
                alt=""
                aria-hidden
                fill
                sizes="100vw"
                className="scale-110 object-cover blur-2xl md:hidden"
              />
            )}
            {slide.artwork && slide.image && (
              <Image
                src={slide.image}
                alt=""
                aria-hidden
                fill
                sizes="100vw"
                className={`scale-110 object-cover blur-2xl ${slide.mobileImage ? "hidden md:block" : ""}`}
              />
            )}
            {slide.video && slide.videoMode === "click" ? (
              // Click-to-play never autoplays, so reduced motion has nothing to protect
              // against — no `!reduced` guard here.
              <ClickToPlayVideo
                src={slide.video}
                poster={slide.image}
                fit={fit}
                label={`Play the video${slide.headline ? `: ${slide.headline}` : ""}`}
              />
            ) : slide.video && !reduced ? (
              <video
                className={`absolute inset-0 h-full w-full ${fit}`}
                src={slide.video}
                poster={slide.image ?? undefined}
                autoPlay
                muted
                loop
                playsInline
                // Without this the browser eagerly downloads the whole file on every
                // visit — it was missing until 2026-08-09.
                preload="metadata"
              />
            ) : slide.image && slide.mobileImage ? (
              <>
                <Image
                  src={slide.mobileImage}
                  alt=""
                  fill
                  priority={i === 0}
                  sizes="100vw"
                  className={`${fit} md:hidden`}
                />
                <Image
                  src={slide.image}
                  alt=""
                  fill
                  priority={i === 0}
                  sizes="100vw"
                  className={`hidden ${fit} md:block`}
                />
              </>
            ) : slide.image ? (
              <Image
                src={slide.image}
                alt=""
                fill
                priority={i === 0}
                sizes="100vw"
                className={fit}
              />
            ) : (
              <div className="absolute inset-0 bg-gradient-to-br from-accent-strong to-foreground" />
            )}
          </>
        );
        return (
          <div
            key={slide.key}
            className={`${i === current ? "opacity-100" : "pointer-events-none opacity-0"} absolute inset-0 transition-opacity duration-700 motion-reduce:transition-none`}
            aria-hidden={i !== current}
          >
            {/* A finished artwork paints its own button, and a painted button that does
              * nothing when tapped is worse than no button — so the whole image is the
              * link. Nothing to click if the CMS left the link empty. */}
            {slide.artwork && slide.ctaHref ? (
              <Link
                href={slide.ctaHref}
                aria-label={slide.headline}
                className="absolute inset-0 focus-visible:outline-2 focus-visible:-outline-offset-4 focus-visible:outline-surface"
                tabIndex={i === current ? undefined : -1}
              >
                {media}
              </Link>
            ) : (
              media
            )}
            {/* Scrims exist to make OUR text legible on a photo. An artwork has no text
              * of ours on it, so darkening it would only dull the artwork. */}
            {!slide.artwork && (
              <>
                <div className="absolute inset-0 bg-gradient-to-r from-black/45 via-black/15 to-transparent" />
                <div className="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-black/30 to-transparent" />
              </>
            )}
            {slide.artwork ? (
              // The pixels carry the headline; the DOM must carry it too. This is the
              // only <h1> on the homepage — deleting it would leave the front door
              // without one, and a screen reader with nothing to announce.
              <h1 className="sr-only">{slide.headline}</h1>
            ) : (
              // No `pointer-events-none`/`auto` pair here: re-enabling events inside a
              // hidden slide un-does the `pointer-events-none` that keeps the four
              // slides nobody is looking at from swallowing clicks meant for the
              // arrows. The z-10 chrome already sits above this layer.
              <div className="absolute inset-0 flex items-center">
                <div className="wrap py-8 md:py-12">
                  {slide.eyebrow && (
                    <p className="mb-3 flex items-center gap-3 text-[11px] font-medium uppercase tracking-[0.22em] text-surface/85 md:mb-5 md:text-xs">
                      <span className="h-px w-8 bg-gold" aria-hidden />
                      {slide.eyebrow}
                    </p>
                  )}
                  <h1 className="max-w-2xl font-display text-3xl leading-[1.05] text-surface sm:text-4xl md:text-5xl lg:text-6xl xl:text-7xl">
                    {slide.headline}
                  </h1>
                  {slide.sub && (
                    <p className="mt-4 max-w-xl text-base leading-relaxed text-surface/90 md:mt-6 md:text-lg">
                      {slide.sub}
                    </p>
                  )}
                  {slide.ctaText && slide.ctaHref && (
                    <div className="mt-6 md:mt-9">
                      <Link
                        href={slide.ctaHref}
                        tabIndex={i === current ? undefined : -1}
                        className="inline-block rounded-full bg-surface px-6 py-3 font-medium text-foreground shadow-sm transition hover:bg-background hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface md:px-8 md:py-3.5"
                      >
                        {slide.ctaText}
                      </Link>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        );
      })}

      {many && (
        <>
          {/* The chrome's own backing. The per-slide scrims are gone on an artwork
            * slide, and white tab labels on pale artwork are unreadable without this. */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-black/45 to-transparent"
          />
          <button
            type="button"
            onClick={() => show(current - 1)}
            aria-label="Previous slide"
            // Hidden on phones: at 390px the two chips land on top of the headline, and
            // the dot row below already changes slides with a bigger tap target.
            className="absolute left-4 top-1/2 z-10 hidden h-11 w-11 -translate-y-1/2 place-items-center rounded-full border border-surface/50 bg-black/35 text-surface transition hover:bg-black/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface sm:grid"
          >
            ‹
          </button>
          <button
            type="button"
            onClick={() => show(current + 1)}
            aria-label="Next slide"
            className="absolute right-4 top-1/2 z-10 hidden h-11 w-11 -translate-y-1/2 place-items-center rounded-full border border-surface/50 bg-black/35 text-surface transition hover:bg-black/60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface sm:grid"
          >
            ›
          </button>
          {/* Numbered title tabs need room for a title. Six of them on a 390px phone
            * left ~35px each and truncated every label to nothing, so phones get dots
            * and the tabs start at md. */}
          <div className="wrap absolute inset-x-0 bottom-4 z-10 flex justify-center gap-2.5 md:hidden">
            {slides.map((slide, i) => (
              <button
                key={slide.key}
                type="button"
                onClick={() => show(i)}
                aria-label={slide.headline}
                aria-current={i === current ? "true" : undefined}
                className={`h-2 rounded-full transition-all ${
                  i === current ? "w-6 bg-surface" : "w-2 bg-surface/50 hover:bg-surface/80"
                }`}
              />
            ))}
          </div>
          <div className="wrap absolute inset-x-0 bottom-6 z-10 hidden gap-4 md:flex lg:gap-7">
            {slides.map((slide, i) => (
              <button
                key={slide.key}
                type="button"
                onClick={() => show(i)}
                aria-current={i === current ? "true" : undefined}
                // `min-w-0`: without it a flex item refuses to shrink below its own
                // longest word, so five tabs on a 768px tablet ran off the right edge
                // and the last two could not be reached. `truncate` only helps once the
                // button is allowed to be narrower than its label.
                className={`relative min-w-0 flex-1 border-t-2 pt-2.5 text-left text-[11px] uppercase tracking-[0.12em] transition-colors ${
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
