import Link from "next/link";
import { FadeUp } from "@/components/motion/Motion";

/** Artifact section: the Glow Set feature beside the toke × natural stack. */
export function FeatureSplit() {
  return (
    <section aria-label="The Glow Set" className="mx-auto max-w-7xl px-4 pb-12">
      <FadeUp>
        <div className="grid gap-4 lg:grid-cols-[1.25fr_1fr]">
          <div className="relative flex min-h-[430px] items-end overflow-hidden rounded-[var(--radius-card)] bg-gradient-to-br from-[#31502f] to-[#12200f]">
            <div className="relative p-10">
              <h2 className="font-display text-4xl text-surface md:text-5xl">The Glow Set</h2>
              <p className="mt-3 max-w-sm text-sm leading-relaxed text-surface/85">
                Brightening oil, daily facial wash and repair cream — the routine our
                community swears by.
              </p>
              <Link
                href="/products?collection=best-sellers"
                className="mt-6 inline-block rounded-full bg-surface px-7 py-3 text-sm font-medium text-foreground transition hover:bg-background focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface"
              >
                Shop the Set
              </Link>
            </div>
          </div>
          <div className="grid gap-4">
            <div className="relative flex items-end overflow-hidden rounded-[var(--radius-card)] bg-gradient-to-br from-[#1f4d33] to-[#0b1f13]">
              <div className="p-6">
                <p className="text-[11px] uppercase tracking-[0.22em] text-surface/70">
                  tokè × natural
                </p>
                <h3 className="mt-1 font-display text-xl text-surface">
                  Grown from nature, proven by science
                </h3>
              </div>
            </div>
            <Link
              href="/products?q=natural"
              className="relative flex items-end overflow-hidden rounded-[var(--radius-card)] bg-gradient-to-br from-[#8a6a3d] to-[#3a2b16] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <div className="p-6">
                <p className="text-[11px] uppercase tracking-[0.22em] text-surface/70">Collection</p>
                <h3 className="mt-1 font-display text-xl text-surface">Toke Naturals</h3>
              </div>
            </Link>
          </div>
        </div>
      </FadeUp>
    </section>
  );
}
