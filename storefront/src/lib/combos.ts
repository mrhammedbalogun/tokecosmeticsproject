/**
 * Combos on the storefront: the types the pages read, and the fetchers that get them.
 *
 * Server-side only (it uses `apiFetch`). Tagged `catalog` alongside the product fetchers
 * rather than under a tag of its own, because a combo's price is DERIVED from catalogue
 * prices — a repricing has to flush combo pages too, and one tag is what makes that
 * automatic. The backend bumps the same cache version for the same reason
 * (`apps/combos/signals.py`).
 */
import { ApiError, apiFetch } from "@/lib/api";

/** What the shop charges for a bundle, and what it saves against buying the parts.
 *  Every field is a money STRING — display verbatim, never re-round in the browser. */
export interface ComboPricing {
  amount: string;
  components_total: string;
  saving: string;
  /** "10.00" — already worked out from the two amounts, not from a stored rate. */
  saving_percent: string;
  currency: string;
}

/** What a customer gets for buying the box. A bundle gives ONE of them.
 *
 *  Optional on every payload below, and read through `comboReward` rather than bare: the
 *  API caches combo responses for 60 s, so for a minute after a deploy this build can be
 *  handed a payload from before the reward was a choice. Everything that existed then
 *  gave a discount. */
export type RewardType = "discount" | "gift";

export interface ComboGift {
  name: string;
  image: string | null;
}

export interface ComboCard {
  name: string;
  slug: string;
  reward_type?: RewardType;
  /** Present only for a gift combo; `null` for one that discounts. */
  gift?: ComboGift | null;
  short_description: string;
  image: string | null;
  is_featured: boolean;
  pricing: ComboPricing | null;
  /** UNITS in the box, not rows: a combo with 1 cleanser and 2 butters counts 3. */
  item_count: number;
  /** Up to four component pictures, for the card's stacked thumbnails. */
  item_images: string[];
  in_stock: boolean;
}

export interface ComboContentItem {
  product_name: string;
  product_slug: string;
  variant_name: string;
  sku: string;
  /** The picked options, e.g. {"Size": "500g", "Pricing option": "Pieces"}. */
  option_values: Record<string, string>;
  quantity: number;
  unit_price: string | null;
  line_total: string | null;
  image: string | null;
  hover_image: string | null;
  short_description: string;
}

export interface ComboDetail {
  name: string;
  slug: string;
  reward_type?: RewardType;
  gift?: ComboGift | null;
  description: string;
  short_description: string;
  image: string | null;
  is_featured: boolean;
  seo_title: string;
  seo_description: string;
  pricing: ComboPricing | null;
  items: ComboContentItem[];
  in_stock: boolean;
  /** How many whole bundles the shelves can fill, capped at 10 for display. */
  max_quantity: number;
}

const COMBO_REVALIDATE = 60; // matches the backend's own catalog cache TTL

export async function getCombos(country: string) {
  return apiFetch<ComboCard[]>("/combos/", {
    country,
    next: { revalidate: COMBO_REVALIDATE, tags: ["catalog", "combos"] },
  });
}

/**
 * The listing page's fetch: a 404 becomes the empty state, anything else still throws.
 *
 * Exactly `fetchPlpPage`'s policy and for the same reason — a 404 here is not a server
 * fault. The concrete case is a DEPLOY WINDOW: the frontends ship from a push to main
 * and the backend from a tag, so for the minutes between them this build can be talking
 * to an API that has never heard of `/combos/`. The header links to this page, so the
 * alternative to an empty state is a visible error page on the live shop.
 *
 * A 500 or a timeout still bubbles — those ARE server faults and hiding them would turn
 * an outage into "we have no combos today".
 */
export async function fetchComboIndex(country: string): Promise<ComboCard[]> {
  try {
    return await getCombos(country);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return [];
    throw err;
  }
}

export async function getCombo(slug: string, country: string) {
  return apiFetch<ComboDetail>(`/combos/${slug}/`, {
    country,
    next: { revalidate: COMBO_REVALIDATE, tags: ["catalog", "combos", `combo:${slug}`] },
  });
}

/* ── What a bundle is worth buying for ──────────────────────────────────────────────
 *
 * Every surface that sells a combo — the card, the page, the homepage row's heading —
 * asks the same question first: WHAT IS THE REWARD? There are two answers and a bundle
 * gives one of them, so the decision is made once, here, and read everywhere. A page
 * that worked it out for itself would eventually disagree with the badge beside it.
 */

/** The gift, when the reward is a gift. `null` for a discount combo.
 *
 *  Falls back to a generic name if a gift combo somehow arrives without one. The backend
 *  forbids that (`combo_gift_reward_needs_a_gift`), so this is not a case that should
 *  occur — but the alternative to a fallback is a badge rendering the empty string on a
 *  live card, and "Free gift included" is true of every combo that reaches it. */
export function comboGift(combo: {
  reward_type?: RewardType;
  gift?: ComboGift | null;
}): ComboGift | null {
  if (combo.reward_type !== "gift") return null;
  const name = combo.gift?.name?.trim();
  return { name: name || "Free gift included", image: combo.gift?.image ?? null };
}

/** The saving a combo actually gives, as a percentage, 0 when there is none to claim.
 *
 *  A combo's price is a STORED AMOUNT, not a computed 10% off, so a box can cost exactly
 *  what its parts cost — `resolve_combo_price` clamps a pinned amount to the component
 *  total, which makes "saves nothing" reachable and "costs more than the parts"
 *  impossible. Every gift combo is in that position by design.
 *
 *  Trusts the API's `saving_percent` WHENEVER IT PARSES, zero included. It is quantized
 *  to 2dp server-side, so a ₦1 saving on a ₦100,000 box legitimately serialises as
 *  "0.00" — recomputing that from the amounts would resurrect it as 0.001 and put "Save
 *  ₦1 · 0% off" back on the card. The amounts are a fallback only for a payload with no
 *  usable field at all (an older cached build), where the alternative is dropping a real
 *  deal. */
export function comboSavingPercent(pricing: ComboPricing | null | undefined): number {
  if (!pricing) return 0;
  const stated = Number(pricing.saving_percent);
  if (Number.isFinite(stated)) return Math.max(stated, 0);
  const total = Number(pricing.components_total);
  const amount = Number(pricing.amount);
  if (!Number.isFinite(total) || !Number.isFinite(amount) || total <= 0) return 0;
  return amount < total ? ((total - amount) / total) * 100 : 0;
}

/** Does this bundle offer the customer anything at all?
 *
 *  A gift always does. A discount combo does only when it actually discounts — the case
 *  that is NOT hypothetical: Toke's Back-to-School Care Pack ran for weeks priced at
 *  exactly its component total, advertising "Save ₦0 · 0% off", because the model had no
 *  way to say "the reward is in the parcel". A combo with no reward still sells on
 *  /combo; it just cannot headline a promotion. */
export function hasReward(combo: ComboCard): boolean {
  return comboGift(combo) !== null || comboSavingPercent(combo.pricing) > 0;
}

/* ── The homepage promo row ──────────────────────────────────────────────────────────
 *
 * The homepage row makes a PROMISE in its heading, so it may only carry combos that keep
 * it: a bundle with no reward to state is dropped, though it stays on /combo, where the
 * heading promises nothing.
 *
 * SOLD-OUT COMBOS ARE KEPT, sorted to the end. The Best Sellers row 200px above shows a
 * "Sold Out" tag rather than hiding the product, and two adjacent rows must not treat
 * "can't buy it" oppositely. Combos also go out of stock far more readily than products
 * — `max_addable` is the minimum across every component, so one dud component empties
 * the box — and with a handful of combos in the catalogue, dropping them would empty the
 * row with nothing on the page to say why.
 *
 * If nothing survives, ComboRow renders nothing at all and the homepage has one section
 * fewer.
 */

/** The combos the homepage row may show: curator's order, sold-out last, capped. */
export function promoCombos(combos: ComboCard[], limit = 8): ComboCard[] {
  // `in_stock` is required by the type but can be missing from a payload cached by an
  // older API build; assume in stock there, as the product cards do.
  const sellable = (c: ComboCard) => c.in_stock !== false;
  return combos
    .filter(hasReward)
    .slice() // `sort` mutates, and this array is the caller's
    .sort((a, b) => Number(sellable(b)) - Number(sellable(a)))
    .slice(0, limit);
}

/** What the row's heading may claim across the combos it is showing.
 *
 *  Both halves can be true at once — a row holding two 10%-off boxes and one gift box
 *  has to sell both ideas in one line — so this reports them separately and lets the
 *  component word it.
 *
 *  `upTo` is the point of the discount half. Toke prices every discount combo at 10% off
 *  today, so the row normally states one exact rate; the day a curator pins one at 15%
 *  the heading has to stop claiming a single number without going silent about the
 *  discount altogether, which is how a dynamic heading quietly stops selling.
 *
 *  Mixed rates are FLOORED, never rounded. Rounding 9.51 to "10%" overstates the offer
 *  against the card's own badge; flooring can only ever understate it. */
export function rewardClaim(combos: ComboCard[]): {
  discount: { percent: number; upTo: boolean } | null;
  gift: boolean;
} {
  const percents = combos.map((c) => comboSavingPercent(c.pricing)).filter((p) => p > 0);
  const gift = combos.some((c) => comboGift(c) !== null);
  if (percents.length === 0) return { discount: null, gift };
  const [first] = percents;
  if (percents.every((p) => p === first)) {
    return { discount: { percent: first, upTo: false }, gift };
  }
  const best = Math.floor(Math.max(...percents));
  return { discount: best > 0 ? { percent: best, upTo: true } : null, gift };
}

/** "10.00" → "10", "9.5" → "9.5". Trailing zeros are noise in a heading or a badge. */
export function formatPercent(percent: number): string {
  return String(Number(percent.toFixed(2)));
}
