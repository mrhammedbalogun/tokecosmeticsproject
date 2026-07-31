/**
 * Shapes and query handling for the admin products list. No fetching — that is
 * `app/(shell)/products/page.tsx`, a Server Component reading through
 * `fetchWithAuthOrBounce`.
 *
 * Pure functions here for the same reason `lib/audit.ts` gives: everything interesting
 * about the trip from `searchParams` to the API — which keys survive, what a blank field
 * means, whether page 1 is written down — is decidable without a request, and every bug in
 * it presents as "the filter silently did nothing". Cheap to test, expensive to notice.
 *
 * THE TWO FILTERS ARE THE BACKEND'S TWO. `ProductAdminViewSet` (Plan-17a Task 1) carries
 * `filterset_fields = ["status"]` and `search_fields = ["name", "variants__sku"]`, so
 * `?search=` and `?status=` are the whole vocabulary. Forwarding anything else would give
 * an operator a control that does nothing.
 */
import { PAGE_SIZE } from "@/lib/pagination";

export { PAGE_SIZE };

/** Product.STATUS in `backend/apps/catalog/models.py`. Order is the lifecycle, not the
 *  alphabet, because that is the order a person thinks about them in. */
export const STATUSES = ["draft", "active", "archived"] as const;
export type ProductStatus = (typeof STATUSES)[number];

export function isProductStatus(value: string): value is ProductStatus {
  return (STATUSES as readonly string[]).includes(value);
}

export interface ProductRow {
  id: number;
  name: string;
  slug: string;
  status: ProductStatus;
  is_featured: boolean;
  updated_at: string;
  /** URL of the first image by position, or null when the product has none. */
  thumbnail: string | null;
  variant_count: number;
  /** Currency codes this product has a currency-level price in. See `unpricedIn`. */
  priced_currencies: string[];
}

export interface ProductPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: ProductRow[];
}

export interface ProductFilters {
  search?: string;
  status?: ProductStatus;
  page: number;
}

export function parseProductFilters(params: URLSearchParams): ProductFilters {
  const filters: ProductFilters = { page: parsePage(params.get("page")) };

  const search = params.get("search")?.trim();
  // Blank is ABSENT, not empty. A GET form submits every field it contains, so without
  // this an untouched form sends `?search=&status=` — two filters that match everything.
  if (search) filters.search = search;

  const status = params.get("status")?.trim();
  // An unrecognised status is DROPPED rather than forwarded. The backend would answer 400
  // for `?status=nonsense`, and an error page is the wrong response to a hand-edited URL
  // when "show everything" is both harmless and obviously what was meant.
  if (status && isProductStatus(status)) filters.status = status;

  return filters;
}

function parsePage(raw: string | null): number {
  // Regex rather than a numeric parse: `Number("")` and `Number(" ")` are both 0, and this
  // rejects "1.5" and "abc" identically with no NaN branch. Same rule as lib/audit.ts.
  if (!raw || !/^\d+$/.test(raw)) return 1;
  const page = Number(raw);
  return page >= 1 ? page : 1;
}

/** The filters as a query string, for both the API call and the pagination links. */
export function productsQueryString(filters: ProductFilters): string {
  const params = new URLSearchParams();
  if (filters.search) params.set("search", filters.search);
  if (filters.status) params.set("status", filters.status);
  // Page 1 is the default on both sides, so omitting it keeps the unfiltered URL clean and
  // makes "am I on the first page" answerable from the address bar.
  if (filters.page > 1) params.set("page", String(filters.page));
  return params.toString();
}

/**
 * The currencies a product is NOT priced in, so the row can say so.
 *
 * Worth a function rather than an inline filter because of what it is for. Production is
 * 121 prices and every one is NGN, which means every product is invisible in the UK, US
 * and Canada for want of a price — and that is not visible anywhere in the admin today.
 * This column is how that stops being invisible.
 */
export function unpricedIn(row: ProductRow, configured: readonly string[]): string[] {
  const priced = new Set(row.priced_currencies);
  return configured.filter((code) => !priced.has(code));
}

/** Human label for a status. The API's values are lowercase machine tokens. */
export function statusLabel(status: ProductStatus): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}
