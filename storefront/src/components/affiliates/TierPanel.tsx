import type { CmsBanner } from "@/lib/cms";
import { TileMedia } from "@/components/home/TileMedia";
import type { EliteTier } from "@/lib/referral-terms";

const PERKS = [
  "Monthly retainer conversations",
  "PR packages and product, on us",
  "First access to new launches",
] as const;

/**
 * The ₦200k Club — a deep-green panel with the artwork beside it, and a gold badge
 * straddling the seam. The composition is lifted from Hammed's reference (2026-08-16);
 * the palette is ours, so `accent-strong` does the work its flat green did.
 *
 * ── NO IMAGE MEANS NO IMAGE HALF, NOT AN EMPTY ONE ──────────────────────────────────
 *
 * `TileMedia` falls back to a brand gradient, which is right on the homepage where a
 * tile has a fixed slot in a grid. Here it would render a large blank rectangle next to
 * the copy, and a reader cannot tell "artwork not uploaded yet" from "broken". So with
 * no banner the panel simply becomes one column and fills the width — a finished-looking
 * layout in both states, which is the whole point of the fallback rule rather than a
 * decorative version of it.
 */
export function TierPanel({ tier, banner }: { tier: EliteTier; banner?: CmsBanner | null }) {
  const hasArt = Boolean(banner?.image || banner?.mobile_image || banner?.video_url);

  return (
    <section aria-labelledby="elite-heading" className="wrap pb-20 sm:pb-28">
      <div
        className={`relative overflow-hidden rounded-[var(--radius-card)] bg-accent-strong ${
          hasArt ? "grid lg:grid-cols-[1.15fr_0.85fr]" : ""
        }`}
      >
        <div className="p-10 sm:p-14 lg:p-16">
          <span className="inline-block rounded-full border border-gold/50 px-3 py-1 text-[10px] font-medium uppercase tracking-[0.22em] text-gold">
            Exclusive tier
          </span>
          <h2
            id="elite-heading"
            className="mt-6 font-display text-4xl leading-[1.05] text-surface sm:text-5xl"
          >
            {tier.club_name}
          </h2>
          <p className="mt-5 max-w-md text-sm leading-relaxed text-surface/75">
            Drive more than {tier.threshold_display} of referred sales in any{" "}
            {tier.window_days}-day window and we&rsquo;ll come to you about partnering
            properly. There&rsquo;s no separate sign-up for this one either — your balance
            gets you there or it doesn&rsquo;t.
          </p>
          <ul className="mt-8 grid gap-3 text-sm text-surface/85">
            {PERKS.map((perk) => (
              <li key={perk} className="flex gap-3">
                <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-gold" />
                {perk}
              </li>
            ))}
          </ul>
        </div>

        {hasArt && (
          <div className="relative min-h-[280px] lg:min-h-full">
            <TileMedia banner={banner} tone="from-[#14401f] to-[#0b2413]" sizes="(max-width: 1024px) 100vw, 45vw" />
            {/* The badge straddles the seam on desktop only: at one column it would sit
                over the artwork's centre with nothing to anchor it to. */}
            <span
              aria-hidden
              className="absolute left-6 top-6 hidden h-24 w-24 place-items-center rounded-full border border-gold/40 bg-accent-strong/90 text-center text-[10px] font-medium uppercase leading-tight tracking-[0.14em] text-gold backdrop-blur lg:-left-12 lg:top-1/2 lg:-translate-y-1/2 lg:grid">
              Brand
              <br />
              ambassador
            </span>
          </div>
        )}
      </div>
    </section>
  );
}
