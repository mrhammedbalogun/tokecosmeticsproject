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
 * NO `href` ON ANY RESULT, deliberately. Plans 17/18 build the order, customer and product
 * detail pages; until they exist a link is a 404 with extra steps. The fields are inline
 * instead, which turns out to be most of the feature: "what is the status of TC-100123"
 * and "which customer is this email" are answerable from the card without navigating
 * anywhere. When those pages land, add hrefs here and in `SearchResultsPanel` — nothing
 * else has to change.
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

export interface SearchResults {
  orders?: OrderResult[];
  customers?: CustomerResult[];
  products?: ProductResult[];
}

export interface SearchState {
  query: string;
  results: SearchResults | null;
  error?: string;
}

export const SECTION_LABELS: Record<keyof SearchResults, string> = {
  orders: "Orders",
  customers: "Customers",
  products: "Products",
};

/** Section order, fixed here rather than taken from the response, so the panel does not
 *  reshuffle between searches when a section happens to come back empty. */
export const SECTION_ORDER: (keyof SearchResults)[] = ["orders", "customers", "products"];

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
