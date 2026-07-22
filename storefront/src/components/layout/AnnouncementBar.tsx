"use client";
import { useEffect, useState } from "react";
import { ANNOUNCEMENTS } from "@/lib/home-content";

/** Section 1: rotating announcement bar. SSR renders the first message (no CLS);
 * rotation pauses for prefers-reduced-motion. aria-live=off — decorative rotation
 * must not spam screen readers. The gold hairline underline is the "seasoning"
 * luxury detail from design-direction.md. */
export function AnnouncementBar() {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const t = setInterval(() => setI((n) => (n + 1) % ANNOUNCEMENTS.length), 5000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="border-b border-accent-strong/40 bg-accent text-surface" aria-live="off">
      <p
        key={i}
        className="mx-auto max-w-7xl px-4 py-2 text-center text-xs font-medium tracking-[0.08em] motion-safe:animate-[announce_0.5s_ease-out]"
      >
        {ANNOUNCEMENTS[i]}
      </p>
    </div>
  );
}
