import type { ReactNode } from "react";
import { WHY_CHOOSE } from "@/lib/home-content";
import { FadeUp } from "@/components/motion/Motion";

/** Section 10: "Why choose Toke" — icon cards on a warm-beige band. Restrained
 * line icons (forest-green stroke) + a thin gold rule = the "seasoning" luxury
 * detail. Icons are decorative (aria-hidden); the title carries the meaning.
 * Six trust pillars from home-content (D3). Keyed on the STABLE `icon` field, not
 * the (freely editable) title — so editing copy can never blank an icon. The
 * exported map is asserted complete by WhyChoose.test.tsx. */
export const ICONS: Record<string, ReactNode> = {
  "clipboard-check": (
    <>
      <path d="M9 4h6a1 1 0 0 1 1 1v1h1a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h1V5a1 1 0 0 1 1-1Z" />
      <path d="m9 13 2 2 4-4" />
    </>
  ),
  leaf: (
    <>
      <path d="M11 20A7 7 0 0 1 4 13c0-5 4-9 16-9 0 8-4 12-9 12Z" />
      <path d="M4 20c2-6 6-9 12-11" />
    </>
  ),
  heart: (
    <path d="M12 20s-7-4.35-9.5-8.5A5 5 0 0 1 12 6a5 5 0 0 1 9.5 5.5C19 15.65 12 20 12 20Z" />
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18Z" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3Z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 12a8 8 0 1 1-2.34-5.66" />
      <path d="M20 4v4h-4" />
    </>
  ),
};

export function WhyChoose() {
  return (
    <section aria-labelledby="why-h" className="bg-beige">
      <div className="mx-auto max-w-7xl px-4 py-16">
        <FadeUp>
          <h2 id="why-h" className="font-display text-3xl md:text-4xl">
            Why choose Toke
          </h2>
        </FadeUp>
        <div className="mt-8 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
          {WHY_CHOOSE.map((w, i) => (
            <FadeUp key={w.title} delay={i * 0.04}>
              <div className="flex h-full flex-col items-center rounded-[var(--radius-card)] bg-surface p-5 text-center shadow-sm">
                <svg
                  aria-hidden
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="h-7 w-7 text-accent"
                >
                  {ICONS[w.icon]}
                </svg>
                <div className="mt-3 h-px w-8 bg-gold" aria-hidden />
                <h3 className="mt-3 text-sm font-semibold">{w.title}</h3>
                <p className="mt-1.5 text-xs leading-relaxed text-muted">{w.body}</p>
              </div>
            </FadeUp>
          ))}
        </div>
      </div>
    </section>
  );
}
