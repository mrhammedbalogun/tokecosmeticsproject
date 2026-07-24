/** searchParams (untrusted URL input) -> a safe, typed SearchParams for the
 * /search endpoint. Distinct from parsePlpParams: the search API uses `q`/`sort`/
 * `in_stock` (NOT the PLP's `ordering`/price). Same whitelisting/coercion discipline. */
import type { SearchParams } from "@/lib/catalog";

type Raw = Record<string, string | string[] | undefined>;

/** Shared URL-param helper: collapse a possibly-repeated param to its first value. */
export const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

/** The three sort options the backend actually supports (relevance is the default
 * when `q` is present, expressed as the absence of `sort`). */
export const SEARCH_SORTS = ["price_asc", "price_desc", "newest"] as const;
type SearchSort = (typeof SEARCH_SORTS)[number];

export function parseSearchParams(raw: Raw): SearchParams {
  const params: SearchParams = {};
  const q = (first(raw.q) ?? "").trim();
  if (q) params.q = q;
  // Coerce page IDENTICALLY to parsePlpParams: integers > 1 only (page=1.5 / NaN /
  // negative all fall back to the default first page — never forwarded verbatim).
  const page = Number(first(raw.page));
  if (Number.isInteger(page) && page > 1) params.page = page;
  const sort = first(raw.sort);
  if (sort && (SEARCH_SORTS as readonly string[]).includes(sort)) params.sort = sort as SearchSort;
  if (first(raw.in_stock) === "1") params.in_stock = "1"; // strict opt-in
  return params;
}
