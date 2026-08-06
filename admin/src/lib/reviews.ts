/**
 * Types + URL filter handling for the Reviews screen (`/reviews`).
 *
 * The page URL and the API request share ONE query-string builder (the products-page
 * pattern): the same names (`status`, `search`, `page`) appear in the browser URL and
 * in `/admin/reviews/?…`, so pagination links and the fetch can't drift apart.
 */

export interface ReviewRow {
  id: number;
  product_name: string;
  product_slug: string;
  author_name: string;
  author_email: string;
  rating: number;
  title: string;
  body: string;
  status: "approved" | "hidden";
  created_at: string;
}

export interface ReviewPage {
  count: number;
  results: ReviewRow[];
}

export interface ReviewFilters {
  /** "" = all. Backend values; the UI labels `approved` as "Visible". */
  status: "" | "approved" | "hidden";
  search: string;
  page: number;
}

export function parseReviewFilters(raw: URLSearchParams): ReviewFilters {
  const status = raw.get("status") ?? "";
  return {
    // An unrecognised value is dropped rather than forwarded (products.ts rule).
    status: status === "approved" || status === "hidden" ? status : "",
    search: (raw.get("search") ?? "").trim(),
    page: Math.max(1, Number(raw.get("page")) || 1),
  };
}

export function reviewsQueryString(filters: ReviewFilters): string {
  const qs = new URLSearchParams();
  if (filters.status) qs.set("status", filters.status);
  if (filters.search) qs.set("search", filters.search);
  if (filters.page > 1) qs.set("page", String(filters.page));
  return qs.toString();
}
