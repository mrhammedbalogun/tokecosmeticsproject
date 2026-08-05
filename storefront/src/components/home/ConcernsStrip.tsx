import Link from "next/link";
import { FadeUp } from "@/components/motion/Motion";

/** Artifact section: three joined wide tiles — start where your skin is. */
const CONCERNS = [
  { label: "Acne", href: "/products?q=acne", tone: "from-[#6b5140] to-[#2a1e16]" },
  { label: "Hyperpigmentation", href: "/products?q=brightening", tone: "from-[#5a463a] to-[#241a12]" },
  { label: "Dry Skin", href: "/products?q=hydrating", tone: "from-[#7d6a53] to-[#33281c]" },
];

export function ConcernsStrip() {
  return (
    <section aria-label="Shop by concern" className="mx-auto max-w-7xl px-4 pb-12">
      <FadeUp>
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted">
          Shop by Concern
        </p>
        <h2 className="mt-1 font-display text-3xl md:text-4xl">Start where your skin is</h2>
        <div className="mt-8 grid gap-0.5 overflow-hidden rounded-[var(--radius-card)] md:grid-cols-3">
          {CONCERNS.map((concern) => (
            <Link
              key={concern.label}
              href={concern.href}
              className={`group relative flex aspect-[16/7] items-center justify-center bg-gradient-to-br ${concern.tone} focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent`}
            >
              <span className="border-b border-surface/60 pb-1.5 text-[13px] uppercase tracking-[0.2em] text-surface transition-colors group-hover:border-leaf group-hover:text-leaf">
                {concern.label}
              </span>
            </Link>
          ))}
        </div>
      </FadeUp>
    </section>
  );
}
