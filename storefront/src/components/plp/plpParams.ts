/** searchParams (untrusted URL input) -> a safe, typed PLP state, and back to hrefs.
 * Shareable/crawlable URLs are the master-spec requirement — ALL state is in the URL. */
import { first } from "@/lib/search-params";

export const ORDERINGS = ["newest", "price_asc", "price_desc", "best_selling"] as const;
export type Ordering = (typeof ORDERINGS)[number];

export interface PlpState {
  brand?: string; tag?: string; collection?: string;
  price_min?: string; price_max?: string;
  ordering?: Ordering; page: number;
}
type Raw = Record<string, string | string[] | undefined>;

export function parsePlpParams(raw: Raw): PlpState {
  const state: PlpState = { page: 1 };
  const page = Number(first(raw.page));
  if (Number.isInteger(page) && page > 1) state.page = page;
  for (const key of ["brand", "tag", "collection"] as const) {
    const v = first(raw[key]);
    if (v) state[key] = v;
  }
  // Prices reach the backend as raw query params → a non-numeric/negative value
  // triggers a Decimal cast error (500). Only forward finite, >= 0 numbers; drop
  // the rest (min > max and other harmless cases simply yield empty results).
  for (const key of ["price_min", "price_max"] as const) {
    const v = first(raw[key]);
    if (v && Number.isFinite(Number(v)) && Number(v) >= 0) state[key] = v;
  }
  const ord = first(raw.ordering);
  if (ord && (ORDERINGS as readonly string[]).includes(ord)) state.ordering = ord as Ordering;
  return state;
}

/** Href for the same PLP with one key changed. Changing anything but `page` resets
 * to page 1 (a new filter set is a new result set). */
export function plpHref(base: string, current: PlpState, patch: Partial<PlpState>): string {
  const next = { ...current, ...patch };
  if (!("page" in patch)) next.page = 1;
  const qs = new URLSearchParams();
  for (const key of ["brand", "tag", "collection", "price_min", "price_max", "ordering"] as const) {
    if (next[key]) qs.set(key, String(next[key]));
  }
  if (next.page > 1) qs.set("page", String(next.page));
  const s = qs.toString();
  return s ? `${base}?${s}` : base;
}
