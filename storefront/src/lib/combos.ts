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

export interface ComboCard {
  name: string;
  slug: string;
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

/** The saving a combo actually gives, as a percentage, 0 when there is none to claim.
 *
 *  A combo's price is a STORED AMOUNT, not a computed 10% off, so a curator can pin a box
 *  at exactly what its parts cost — `resolve_combo_price` clamps a pinned amount to the
 *  component total (`apps/combos/services.py`), which makes "saves nothing" reachable and
 *  "costs more than the parts" impossible. Toke's Back-to-School Care Pack is one such
 *  box today, and it was advertising "Save ₦0 · 0% off".
 *
 *  Trusts the API's `saving_percent` WHENEVER IT PARSES, zero included. It is quantized
 *  to 2dp server-side, so a ₦1 saving on a ₦100,000 box legitimately serialises as
 *  "0.00" — recomputing that from the amounts would resurrect it as 0.001 and put "Save
 *  ₦1 · 0% off" back on the card. The amounts are a fallback only for a payload with no
 *  usable field at all (an older cached build), where the alternative is dropping a real
 *  deal. */
export function comboSavingPercent(pricing: ComboPricing | null): number {
  if (!pricing) return 0;
  const stated = Number(pricing.saving_percent);
  if (Number.isFinite(stated)) return Math.max(stated, 0);
  const total = Number(pricing.components_total);
  const amount = Number(pricing.amount);
  if (!Number.isFinite(total) || !Number.isFinite(amount) || total <= 0) return 0;
  return amount < total ? ((total - amount) / total) * 100 : 0;
}

/** "10.00" → "10", "9.5" → "9.5". Trailing zeros are noise in a badge. */
export function formatPercent(percent: number): string {
  return String(Number(percent.toFixed(2)));
}
