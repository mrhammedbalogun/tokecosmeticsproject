/**
 * Shapes and labels for the global search box. No fetching here — see
 * `app/(shell)/search-actions.ts`.
 *
 * THE RESPONSE ONLY CONTAINS SECTIONS THE CALLER'S SCOPES ALLOW, which is why every field
 * below is optional and why nothing in this app filters sections itself. The backend
 * derives each section's scope from that section's own list endpoint
 * (`apps/core/admin_search.py`), so a section that is absent is absent because the person
 * may not see it — and re-deciding that here would put a second, weaker copy of the rule
 * in a bundle the browser can read.
 *
 * THE HREFS ARE BUILT HERE, NOT SENT BY THE API, and that is the arrangement the backend
 * docstring asks for rather than an oversight on its part: `/orders/[number]` is a Next
 * route in this app, and an API that hard-coded it would have to be redeployed to rename a
 * page. The response carries the IDENTIFIERS; `resultHref` below turns them into routes.
 *
 * The fields stay inline beside the link. They were the whole feature while the detail
 * pages did not exist, and they are still the fast path: "what is the status of TC-100123"
 * and "which customer is this email" are answered on the card, and the link is there for
 * when the answer is "open it".
 */

/** Kept in step with `MIN_TERM_LENGTH` in `backend/apps/core/admin_search.py`. */
export const MIN_QUERY_LENGTH = 3;

/** How long the box waits after the last keystroke. UX only — the server-side cap is the
 *  control (`AdminSearchThrottle`, 60/min per staff user). */
export const SEARCH_DEBOUNCE_MS = 250;

export interface OrderResult {
  number: string;
  legacy_number: string;
  status: string;
  grand_total: string;
  currency: string;
  email: string;
  placed_at: string;
}

export interface CustomerResult {
  toke_id: string;
  email: string;
  name: string;
  is_active: boolean;
  date_joined: string;
}

export interface ProductResult {
  name: string;
  slug: string;
  status: string;
  skus: string[];
}

/** A bundle.
 *
 *  NO PRICE FIELD, and that is the backend being honest rather than the type being thin:
 *  a combo's price is resolved per market from what its components cost there today, so
 *  there is no single number to put on a card. `item_count` is UNITS in the box (1
 *  cleanser + 2 butters is 3), matching what the storefront card states. */
export interface ComboResult {
  name: string;
  slug: string;
  status: string;
  reward_type: "discount" | "gift";
  item_count: number;
  /** Up to three of the things inside, named both ways: the product for a human, the SKU
   *  for whoever typed one in to find out which bundle is holding a variant. */
  items: { product: string; sku: string }[];
}

export interface SearchResults {
  orders?: OrderResult[];
  customers?: CustomerResult[];
  products?: ProductResult[];
  combos?: ComboResult[];
}

/** Any one result row, whichever section it came from. */
export type SearchRow = OrderResult | CustomerResult | ProductResult | ComboResult;

export interface SearchState {
  query: string;
  results: SearchResults | null;
  error?: string;
}

export const SECTION_LABELS: Record<keyof SearchResults, string> = {
  orders: "Orders",
  customers: "Customers",
  products: "Products",
  combos: "Combos",
};

/** Section order, fixed here rather than taken from the response, so the panel does not
 *  reshuffle between searches when a section happens to come back empty. */
export const SECTION_ORDER: (keyof SearchResults)[] = [
  "orders",
  "customers",
  "products",
  "combos",
];

/**
 * Where a result row goes when it is clicked, or `null` for one that cannot be linked.
 *
 * A LINK ADDS NO REACH, which is what makes this safe to do without a second thought about
 * scopes. A section only appears in the response when the caller holds the scope that
 * section's list endpoint requires (`apps/core/admin_search.py`), and each detail page
 * below sits behind that same scope — so every href here points somewhere the caller has
 * already been shown they may go. Linking a section the browser filtered in would be the
 * bug; nothing here filters anything.
 *
 * `null` RATHER THAN A HALF-BUILT PATH when the identifier is missing. `/orders/` is the
 * order QUEUE, so a row with no number would quietly send somebody to a list of everything
 * — a mis-navigation that looks like a working link, which is worse than no link at all.
 *
 * A section added to `SearchResults` without a case here falls through to `null` and
 * renders unlinked. That is the right failure: a missing link is a small annoyance, a link
 * to a route that does not exist is a 404 in somebody's face.
 */
export function resultHref(section: keyof SearchResults, row: SearchRow): string | null {
  // `encodeURIComponent` on values that are already slug- and code-shaped changes nothing
  // today. It is here because these are DATA, not constants — the same reason
  // `customers/[tokeId]/page.tsx` encodes the id when it builds its API path.
  const path = (base: string, id: string | undefined) =>
    id ? `${base}/${encodeURIComponent(id)}` : null;
  switch (section) {
    case "orders":
      return path("/orders", (row as OrderResult).number);
    case "customers":
      return path("/customers", (row as CustomerResult).toke_id);
    case "products":
      return path("/products", (row as ProductResult).slug);
    case "combos":
      return path("/combos", (row as ComboResult).slug);
    default:
      return null;
  }
}

export function totalResults(results: SearchResults | null): number {
  if (!results) return 0;
  return SECTION_ORDER.reduce((sum, key) => sum + (results[key]?.length ?? 0), 0);
}

/** `pending_payment` → `Pending payment`. The API's vocabulary is snake_case and the
 *  storefront never shows these, so there is no shared map to reuse. */
export function humanStatus(status: string): string {
  const spaced = status.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Money arrives as a STRING from the API — deliberately, so a Decimal never becomes a
 *  float — and is shown as one. No `Intl.NumberFormat`: the value is already formatted to
 *  the currency's own decimal places by Django, and re-parsing it into a Number here is
 *  the one step that could round somebody's refund. */
export function formatMoney(amount: string, currency: string): string {
  return `${currency} ${amount}`;
}
