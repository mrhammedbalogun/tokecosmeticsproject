/**
 * "Shop By Edit" — the three listings that are COMPUTED rather than curated.
 *
 * Each one is a query over the whole catalogue: what sold most, what arrived last, what is
 * reduced today. Nobody files a product into them and nobody has to remember to take it
 * out again, which is the entire reason they are not categories. The menu group that
 * points at them lives in `shop-menu.ts`; this file is what those pages ARE.
 *
 * The other two entries in that menu group are not here because they are not listings:
 * Combo Deals is an existing page (`/combo`) and Travel Sizes is a real category.
 */
import type { ProductListParams } from "@/lib/catalog";
import type { Ordering } from "@/components/plp/plpParams";

export interface ShopEdit {
  slug: string;
  /** <h1> and the metadata title. */
  title: string;
  /** The small caps line above the title. */
  kicker: string;
  blurb: string;
  metaDescription: string;
  /** List params this edit forces on top of whatever the shopper filtered. */
  params: ProductListParams;
  /** Set when the ORDER is the point of the page, which hides the sort control: sorting
   *  "Best Sellers" by price ascending leaves a page called Best Sellers that is not one. */
  fixedOrdering?: Ordering;
  /** Shown instead of the grid when the query comes back empty. */
  empty: string;
}

export const SHOP_EDITS: Record<string, ShopEdit> = {
  "best-sellers": {
    slug: "best-sellers",
    title: "Best Sellers",
    kicker: "What everyone is buying",
    blurb:
      "Ranked by what has actually left the shelf over the last three months — real orders, not a list somebody curated. It reshuffles itself as buying changes.",
    metaDescription:
      "The Toke Cosmetics products selling most right now, ranked by real orders from the last three months.",
    params: { ordering: "best_selling" },
    fixedOrdering: "best_selling",
    // Reached only in a market with no order history at all — every other market falls
    // back to newest-first inside the same query, so the page still fills.
    empty: "Nothing has sold here yet. Browse the full range instead.",
  },
  "new-arrivals": {
    slug: "new-arrivals",
    title: "New Arrivals",
    kicker: "Newest in the shop",
    blurb:
      "Everything in the order it joined the shop, newest first — the latest additions to the range at the top.",
    metaDescription:
      "The newest Toke Cosmetics products, most recently added first — skincare, hair and family care for melanin-rich skin.",
    // Newest-first over the WHOLE catalogue, with NO recency window. The publish dates
    // are the real WordPress ones and the most recent is months old, so a "last 90 days"
    // window — the obvious first instinct — would render this page empty most of the year.
    params: { ordering: "newest" },
    fixedOrdering: "newest",
    empty: "Nothing to show here yet. Browse the full range instead.",
  },
  promo: {
    slug: "promo",
    title: "Promo",
    kicker: "Reduced right now",
    blurb:
      "Everything carrying a reduced price today. A product appears here the moment a was-price is set against it in this market, and leaves when the sale ends.",
    metaDescription:
      "Toke Cosmetics products on promotion right now — every item currently carrying a reduced price.",
    params: { on_sale: "1" },
    // Sorting is free here: the SET is the point of the page, not the order.
    empty:
      "No promotions are running right now. New offers are set from the shop side and appear here the moment they start.",
  },
};

export const shopEdit = (slug: string): ShopEdit | undefined => SHOP_EDITS[slug];
