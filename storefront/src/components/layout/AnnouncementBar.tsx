"use client";
import { useEffect, useState } from "react";
import { ANNOUNCEMENTS } from "@/lib/home-content";

/** Section 1: rotating announcement bar. SSR renders the first message (no CLS);
 * rotation pauses for prefers-reduced-motion. aria-live=off — decorative rotation
 * must not spam screen readers.
 *
 * Zero-CLS layout: the bar reserves a fixed height (min-h-9) and the message is
 * forced single-line (truncate = nowrap + ellipsis), so messages of differing
 * length never wrap to a 2nd line and shift the page every 5s — and long copy on
 * narrow phones ellipsises instead of causing horizontal scroll. */
export function AnnouncementBar() {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const t = setInterval(() => setI((n) => (n + 1) % ANNOUNCEMENTS.length), 5000);
    return () => clearInterval(t);
  }, []);
  return (
    <div
      className="flex min-h-9 items-center justify-center border-b border-accent-strong/40 bg-accent text-surface"
      aria-live="off"
    >
      <p
        key={i}
        className="w-full max-w-7xl truncate px-4 text-center text-xs font-medium tracking-[0.08em] motion-safe:animate-[announce_0.5s_ease-out]"
      >
        {ANNOUNCEMENTS[i]}
      </p>
    </div>
  );
}
