/**
 * Shapes and arithmetic for the combo admin.
 *
 * ── THE PRICING MATH IS DUPLICATED HERE ON PURPOSE ──────────────────────────────────
 *
 * `backend/apps/combos/services.resolve_combo_price` is the authority — it is what the
 * storefront reads and what checkout charges. What lives here is the LIVE PREVIEW: the
 * builder recomputes "components total → N% off → your price" on every keystroke and
 * every quantity change, and a round trip per keystroke would make the panel unusable.
 *
 * The duplication is bounded and deliberate, and the rule that keeps it honest is that
 * nothing here is ever SAVED as a computed number: the preview is thrown away, the server
 * recomputes from `discount_percent` and the item list on write, and the editor then
 * re-renders from the server's own `pricing` block. If the two ever disagree, the screen
 * shows the server's answer within one save.
 *
 * `roundHalfUp` mirrors `q2` in the backend (ROUND_HALF_UP to 2dp) rather than using
 * JavaScript's `toFixed`, which rounds half-to-even on some values and would put the
 * preview a kobo away from the price the shop actually charges.
 */

export const STATUSES = ["draft", "active", "archived"] as const;
export type ComboStatus = (typeof STATUSES)[number];

export function isComboStatus(value: string): value is ComboStatus {
  return (STATUSES as readonly string[]).includes(value);
}

/** Every market the pricing panel has a column for. Same four the pricing model is built
 *  around (`core/migrations/0003_seed_countries_currencies.py`); the editor gets the live
 *  list from `/meta/countries/` and only uses this for a stable column order. */
export const MARKET_ORDER = ["NG", "GB", "US", "CA"] as const;

export interface ComboRow {
  id: number;
  name: string;
  slug: string;
  status: ComboStatus;
  is_featured: boolean;
  position: number;
  discount_percent: string;
  image_url: string | null;
  item_count: number;
  /** Empty means EVERY market — see `Combo.available_countries`. */
  markets: string[];
  updated_at: string;
}

export interface ComboPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: ComboRow[];
}

/** A variant's price in each market; `null` where it is not priced at all. */
export type PriceByMarket = Record<string, string | null>;

export interface ComboItemRow {
  id?: number;
  variant: number;
  quantity: number;
  position?: number;
  product_name: string;
  product_slug: string;
  variant_name: string;
  sku: string;
  option_values: Record<string, string>;
  image: string | null;
  prices: PriceByMarket;
}

export interface MarketPricing {
  components_total: string;
  amount: string;
  saving: string;
  saving_percent: string;
  currency: string;
  pinned: boolean;
}

export interface ComboDetail {
  id: number;
  name: string;
  slug: string;
  description: string;
  short_description: string;
  status: ComboStatus;
  is_featured: boolean;
  position: number;
  discount_percent: string;
  available_countries: string[];
  seo_title: string;
  seo_description: string;
  published_at: string | null;
  image_url: string | null;
  items: ComboItemRow[];
  prices: { country: string; amount: string }[];
  /** Per-market truth from the server; `null` for a market the combo cannot be priced in. */
  pricing: Record<string, MarketPricing | null>;
  /** Whether the shop would actually SHOW it, per market. Deliberately separate from
   *  `pricing`: the two can disagree — a bundle holding a switched-off variant prices
   *  perfectly and is still refused, so a builder reading `pricing` alone sees a healthy
   *  number for something no customer can ever see. */
  live?: Record<string, boolean>;
  /** Market-independent reasons it is not on sale, in plain sentences. Per-market
   *  problems stay in the pricing panel, which already has a row for them.
   *
   *  Optional because a rolling deploy can put this admin build in front of a backend
   *  that predates the field — for the ~minute that lasts, the banner is simply absent
   *  rather than the page being a runtime error on `undefined.length`. */
  blockers?: string[];
  created_at: string;
  updated_at: string;
}

export interface PickerVariant {
  id: number;
  name: string;
  sku: string;
  option_values: Record<string, string>;
  image: string | null;
  prices: PriceByMarket;
}

export interface PickerProduct {
  id: number;
  name: string;
  slug: string;
  image: string | null;
  variants: PickerVariant[];
}

/** Half-up to 2dp, matching the backend's `q2`. Returns a plain number. */
export function roundHalfUp(value: number): number {
  const scaled = value * 100;
  // `Math.round` is half-up for positives, which is every amount this handles; the
  // epsilon absorbs the float error that makes 18.005*100 land at 1800.4999999999998.
  return Math.round(scaled + Number.EPSILON * Math.abs(scaled)) / 100;
}

/**
 * What the picked items cost in one market, or `null` when any of them is unpriced there.
 *
 * `null` rather than a partial sum, exactly as the backend does it: a bundle missing one
 * component's price is unpriceable, not cheap. The panel turns the null into "cannot be
 * sold in the UK yet", which is a far more useful thing to be told while building than
 * after publishing.
 */
export function componentsTotal(
  items: readonly Pick<ComboItemRow, "quantity" | "prices">[],
  market: string,
): number | null {
  if (!items.length) return null;
  let total = 0;
  for (const item of items) {
    const price = item.prices[market];
    if (price == null) return null;
    total += roundHalfUp(Number(price)) * item.quantity;
  }
  return roundHalfUp(total);
}

/** The auto price: `percent` off the component total. */
export function autoPrice(total: number, percent: number): number {
  return roundHalfUp((total * (100 - percent)) / 100);
}

export interface MarketPreview {
  market: string;
  componentsTotal: number | null;
  /** What the shop would charge — the pinned amount when there is one, else the auto price. */
  amount: number | null;
  saving: number | null;
  savingPercent: number | null;
  pinned: boolean;
}

/**
 * The whole pricing panel in one function: for each market, what the parts cost, what the
 * combo costs, and what that saves.
 *
 * A pinned amount above the component total is CLAMPED here as well as on the server, so
 * the preview never shows a negative saving while the server would have shown zero.
 */
export function previewPricing(
  items: readonly Pick<ComboItemRow, "quantity" | "prices">[],
  markets: readonly string[],
  discountPercent: number,
  pinned: Readonly<Record<string, string>>,
): MarketPreview[] {
  return markets.map((market) => {
    const total = componentsTotal(items, market);
    if (total === null) {
      return {
        market, componentsTotal: null, amount: null, saving: null,
        savingPercent: null, pinned: pinned[market] !== undefined,
      };
    }
    const override = pinned[market];
    const isPinned = override !== undefined && override !== "";
    const raw = isPinned ? roundHalfUp(Number(override)) : autoPrice(total, discountPercent);
    const amount = Math.min(Math.max(raw, 0), total);
    const saving = roundHalfUp(total - amount);
    return {
      market,
      componentsTotal: total,
      amount,
      saving,
      savingPercent: total > 0 ? roundHalfUp((saving * 100) / total) : 0,
      pinned: isPinned,
    };
  });
}

/** Markets in `MARKET_ORDER` first, then anything else alphabetically — so the columns
 *  do not reshuffle when a fifth market is added. */
export function orderMarkets(codes: readonly string[]): string[] {
  const known = MARKET_ORDER.filter((m) => codes.includes(m));
  const rest = codes.filter((c) => !(MARKET_ORDER as readonly string[]).includes(c)).sort();
  return [...known, ...rest];
}

/** A one-line description of what a variant is, for a picker row: "500g · Pieces". */
export function optionSummary(options: Record<string, string>, fallback: string): string {
  const parts = Object.values(options ?? {}).filter(Boolean);
  return parts.length ? parts.join(" · ") : fallback;
}

export function comboQueryString(filters: { search?: string; status?: string; page: number }): string {
  const params = new URLSearchParams();
  if (filters.search) params.set("search", filters.search);
  if (filters.status) params.set("status", filters.status);
  if (filters.page > 1) params.set("page", String(filters.page));
  return params.toString();
}
