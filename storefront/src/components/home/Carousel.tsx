"use client";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

/** CSS scroll-snap carousel with arrow controls — the ONLY carousel mechanism in
 * this plan (no carousel library: Lighthouse budget). Children are the slides;
 * each child is expected to set its own snap-start + fixed basis. The track is a
 * native overflow-x scroller, so touch/trackpad swipe works for free and the
 * arrows are a progressive enhancement (hidden on mobile where swipe is natural).
 *
 * Accessibility: role="group" + aria-label names the region; the track is
 * keyboard-scrollable (focusable, arrow keys) and carries its own aria-label so
 * the focused region announces. Each arrow is a real <button> with an aria-label.
 * Arrows disable at their end and hide entirely when the track doesn't overflow,
 * so they are never dead controls. prefers-reduced-motion is honoured in JS —
 * scrollBy's smooth behaviour is a JS option that bypasses the CSS catch-all, so
 * we switch it to "auto" for those users. */
export function Carousel({ children, label }: { children: ReactNode; label: string }) {
  const track = useRef<HTMLDivElement>(null);
  const [overflowing, setOverflowing] = useState(false);
  const [atStart, setAtStart] = useState(true);
  const [atEnd, setAtEnd] = useState(false);

  const sync = useCallback(() => {
    const el = track.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    setOverflowing(max > 1);
    setAtStart(el.scrollLeft <= 1);
    setAtEnd(el.scrollLeft >= max - 1);
  }, []);

  useEffect(() => {
    sync();
    const el = track.current;
    if (!el) return;
    el.addEventListener("scroll", sync, { passive: true });
    window.addEventListener("resize", sync);
    return () => {
      el.removeEventListener("scroll", sync);
      window.removeEventListener("resize", sync);
    };
  }, [sync]);

  const nudge = (dir: 1 | -1) => {
    const el = track.current;
    if (!el) return;
    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollBy({
      left: dir * el.clientWidth * 0.8,
      behavior: reduced ? "auto" : "smooth",
    });
  };

  const arrow =
    "absolute top-1/3 hidden h-10 w-10 place-items-center rounded-full bg-surface text-lg text-foreground shadow-md transition hover:bg-beige focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-0 md:grid";

  return (
    <div role="group" aria-label={label} className="relative">
      <div
        ref={track}
        tabIndex={0}
        aria-label={label}
        className="flex snap-x snap-mandatory gap-4 overflow-x-auto scroll-smooth pb-2 [-ms-overflow-style:none] [scrollbar-width:none] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent [&::-webkit-scrollbar]:hidden"
      >
        {children}
      </div>
      {overflowing && (
        <>
          <button
            type="button"
            onClick={() => nudge(-1)}
            disabled={atStart}
            aria-label={`Scroll ${label} back`}
            className={`-left-3 ${arrow}`}
          >
            <span aria-hidden>←</span>
          </button>
          <button
            type="button"
            onClick={() => nudge(1)}
            disabled={atEnd}
            aria-label={`Scroll ${label} forward`}
            className={`-right-3 ${arrow}`}
          >
            <span aria-hidden>→</span>
          </button>
        </>
      )}
    </div>
  );
}
