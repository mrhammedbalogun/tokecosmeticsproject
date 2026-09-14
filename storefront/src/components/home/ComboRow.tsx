import Link from "next/link";
import { Carousel } from "@/components/home/Carousel";
import { ComboCard } from "@/components/combo/ComboCard";
import { FadeUp } from "@/components/motion/Motion";
import {
  formatPercent,
  promoCombos,
  rewardClaim,
  type ComboCard as ComboCardData,
} from "@/lib/combos";

/**
 * The homepage's Combo Deals row — the Best Sellers row's twin, carrying bundles.
 *
 * Same shape, deliberately: eyebrow, display heading, "View all →", a snap carousel of
 * cards. Two promo rows on one page that scrolled differently would read as two websites.
 * What differs is the card (ComboCard, 4:3 with the contents stacked along the bottom)
 * and therefore the slide width — a product card is a tall 3:4 and a combo card is wide,
 * so they cannot share `sm:w-72` without squashing the box shot.
 *
 * The heading sells whatever the row is actually offering (see `rewardClaim`): one rate
 * when every combo agrees on it, "up to" the best when they differ, the gift when the
 * row is gift bundles, and both when it is a mix. It keeps naming the reward in every
 * case rather than falling back to something vague, and each card's badge carries its
 * own exact figure.
 *
 * The header carries no supporting paragraph, exactly like Best Sellers: "View all" sits
 * on the heading's baseline, and a third line of copy pushed it down on desktop and onto
 * the copy's last line on a phone. What the combo IS gets said on the cards and again at
 * the top of /combo.
 *
 * Renders NOTHING when no combo qualifies — an empty "Combo Deals" heading on the
 * homepage is worse than no section.
 */
/** The heading, for every combination of rewards the row can be holding.
 *
 *  The no-reward line is unreachable through ComboRow — `promoCombos` drops a combo that
 *  offers nothing, so an empty claim means an empty row and the section does not render
 *  — but it is the honest thing to say if this is ever called with one, and a heading
 *  function that could return `undefined` would be worse. */
export function rowTitle(combos: ComboCardData[]): string {
  const { discount, gift } = rewardClaim(combos);
  const rate = discount
    ? `Save ${discount.upTo ? "up to " : ""}${formatPercent(discount.percent)}%`
    : null;
  if (rate && gift) return `${rate} or get a free gift`;
  if (rate) return `${rate} when you buy the set`;
  if (gift) return "Every set comes with a free gift";
  return "Buy the set, keep the change";
}

export function ComboRow({ combos }: { combos: ComboCardData[] }) {
  const shown = promoCombos(combos);
  if (shown.length === 0) return null;
  const title = rowTitle(shown);

  return (
    <section aria-label="Combo Deals" className="wrap py-16">
      <FadeUp>
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="mb-1 text-xs font-medium uppercase tracking-[0.18em] text-muted">
              Combo Deals
            </p>
            <h2 className="font-display text-3xl md:text-4xl">{title}</h2>
          </div>
          <Link
            href="/combo"
            className="shrink-0 text-sm font-medium text-accent transition-colors hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            View all →
          </Link>
        </div>
      </FadeUp>
      <div className="mt-8">
        <Carousel label="Combo Deals">
          {shown.map((combo) => (
            // Sized as a fraction of the row, NOT a fixed `sm:w-80`: `.wrap` is
            // full-bleed with no max-width, so three fixed-width cards huddled at the
            // left of a 1440px screen under a full-width heading — and the carousel
            // hid its arrows, correctly, because nothing overflowed. Three across
            // fills the row at desktop; a fourth combo starts it scrolling.
            <div
              key={combo.slug}
              className="w-[78vw] shrink-0 snap-start sm:w-[calc((100%-1rem)/2)] lg:w-[calc((100%-2rem)/3)]"
            >
              <ComboCard combo={combo} />
            </div>
          ))}
        </Carousel>
      </div>
    </section>
  );
}
