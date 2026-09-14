import { comboGift, comboSavingPercent, formatPercent, type ComboCard, type ComboPricing } from "@/lib/combos";
import { formatMoney } from "@/lib/country";

/**
 * The one claim a bundle makes, in the one place it makes it.
 *
 * A combo rewards a shopper with money off OR with something extra in the parcel, and
 * every surface that sells one has a single badge slot to say which. Routing both
 * answers through one component is what stops a page drawing a saving badge on a gift
 * bundle, or nothing at all on a bundle that has a reward it forgot to look for.
 *
 * RENDERS NOTHING when there is no reward to claim. A curator can price a box at exactly
 * what its parts cost (the backend clamps a pinned amount to the component total), and
 * "Save ₦0 · 0% off" is a worse badge than no badge — that is not hypothetical, it is
 * what Toke's Back-to-School Care Pack advertised for weeks before the reward became a
 * choice.
 */
export function ComboRewardBadge({
  combo,
  size = "md",
}: {
  combo: Pick<ComboCard, "reward_type" | "gift" | "pricing">;
  size?: "sm" | "md";
}) {
  const gift = comboGift(combo);
  if (gift) return <GiftBadge name={gift.name} size={size} />;
  if (!combo.pricing) return null;
  return <SavingBadge pricing={combo.pricing} size={size} />;
}

const shell = (size: "sm" | "md") =>
  `inline-flex max-w-full items-center gap-1.5 rounded-full px-2.5 py-1 font-semibold ${
    size === "sm" ? "text-[10px]" : "text-xs"
  }`;

/** "Save ₦2,000 · 10% off".
 *
 * `saving_percent` comes from the API already worked out FROM THE TWO AMOUNTS, not from
 * a stored rate: a combo pinned at a price no longer equal to "10% off" must advertise
 * the discount it actually gives. Trailing zeros are trimmed so "10.00%" reads "10%". */
export function SavingBadge({
  pricing,
  size = "md",
}: {
  pricing: ComboPricing;
  size?: "sm" | "md";
}) {
  const percent = comboSavingPercent(pricing);
  if (percent <= 0) return null;
  return (
    <span className={`${shell(size)} bg-accent text-white`}>
      <svg viewBox="0 0 16 16" aria-hidden="true" className="h-3 w-3 shrink-0 fill-current">
        <path d="M13.3 7.1 8.9 2.7a1.5 1.5 0 0 0-1-.4H4a1.5 1.5 0 0 0-1.5 1.5v3.9c0 .4.1.7.4 1l4.4 4.4a1.5 1.5 0 0 0 2.1 0l3.9-3.9a1.5 1.5 0 0 0 0-2.1ZM5.2 6a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z" />
      </svg>
      Save {formatMoney(pricing.saving, pricing.currency)}
      <span className="opacity-80">· {formatPercent(percent)}% off</span>
    </span>
  );
}

/** "🎁 Free Kids Hair Grow Cream (50ml)".
 *
 * GOLD, not the accent green the saving badge uses. The two rewards sit side by side in
 * one homepage row, and a shopper scanning it has to be able to tell at a glance which
 * boxes are cheaper and which come with something — two identical green pills would make
 * that a reading exercise. Gold is the house's "seasoning" colour (the Bestseller flag
 * on a product card is the same).
 *
 * The gift's name is the curator's own words and can be long, so it truncates rather
 * than wrapping a pill into three lines; `title` keeps the full text reachable.
 *
 * AN INLINE SVG, NOT A 🎁. The saving badge beside it already draws its own tag icon for
 * the reason this one does: an emoji is a font lookup, and a device without that glyph
 * renders the shop's one promotional badge with a tofu box in front of it. Measured on a
 * headless Chromium, which is exactly such a device.
 */
export function GiftBadge({ name, size = "md" }: { name: string; size?: "sm" | "md" }) {
  return (
    <span className={`${shell(size)} bg-gold text-foreground shadow-sm`} title={name}>
      <svg viewBox="0 0 16 16" aria-hidden="true" className="h-3 w-3 shrink-0 fill-current">
        <path d="M14 6h-1.1c.07-.22.1-.46.1-.7A2.3 2.3 0 0 0 10.7 3c-.9 0-1.5.4-2.7 1.8C6.8 3.4 6.2 3 5.3 3A2.3 2.3 0 0 0 3 5.3c0 .24.03.48.1.7H2a1 1 0 0 0-1 1v1.5h6.2V6H8.8v2.2H15V7a1 1 0 0 0-1-1Zm-8.7 0a.7.7 0 1 1 0-1.4c.3 0 .6.1 1.7 1.4H5.3Zm5.4 0H9c1.1-1.3 1.4-1.4 1.7-1.4a.7.7 0 1 1 0 1.4ZM1.8 9.5V14a1 1 0 0 0 1 1h4.4V9.5H1.8Zm7 5.5h4.4a1 1 0 0 0 1-1V9.5H8.8V15Z" />
      </svg>
      <span className="truncate">{name}</span>
    </span>
  );
}
