/**
 * Shapes and query handling for the store directory (Plan-42). No fetching — that is
 * `app/(shell)/find-stores/page.tsx`, a Server Component reading through
 * `fetchWithAuthOrBounce`.
 *
 * Pure functions here for the reason `lib/products.ts` gives: the whole trip from
 * `searchParams` to the API — which keys survive, what a blank field means, whether an
 * unrecognised value is dropped or forwarded — is decidable without a request, and
 * every bug in it presents as "the filter silently did nothing".
 *
 * THE FILTER VOCABULARY IS THE BACKEND'S. `StoreLocationFilter` carries `country`
 * (ISO code), `state_region`, `area_region`, `store_type`, `status` and `q`; nothing
 * else is forwarded, because a control that does nothing is worse than no control.
 *
 * ── THE STATUS DEFAULT IS A REAL DECISION ───────────────────────────────────────────
 *
 * Sending NO `status` is not the same as sending `all`. The viewset hides archived rows
 * when the parameter is absent, so "Any" here means "the live directory" and archived
 * rows are reached deliberately, by asking. That is why `STATUSES` has four entries and
 * the blank option is labelled for what it does.
 */
import { PAGE_SIZE } from "@/lib/pagination";

export { PAGE_SIZE };

/** `stores.models.STORE_TYPE_CHOICES`. */
export const STORE_TYPES = ["toke_store", "distributor"] as const;
export type StoreType = (typeof STORE_TYPES)[number];

export function isStoreType(value: string): value is StoreType {
  return (STORE_TYPES as readonly string[]).includes(value);
}

export function storeTypeLabel(value: StoreType): string {
  return value === "toke_store" ? "Toke Store" : "Authorized Distributor";
}

/** `stores.filters.STATUS_CHOICES`. Lifecycle order, not alphabetical. */
export const STATUSES = ["active", "inactive", "archived", "all"] as const;
export type StoreStatus = (typeof STATUSES)[number];

export function isStoreStatus(value: string): value is StoreStatus {
  return (STATUSES as readonly string[]).includes(value);
}

export function statusLabel(value: StoreStatus): string {
  switch (value) {
    case "active":
      return "Active";
    case "inactive":
      return "Inactive";
    case "archived":
      return "Archived";
    default:
      return "All, including archived";
  }
}

/** The row shape `StoreLocationAdminSerializer` returns. */
export interface StoreRow {
  id: number;
  name: string;
  store_type: StoreType;
  store_type_label: string;
  country: string;
  country_name: string;
  state_region: number;
  state_name: string;
  area_region: number | null;
  area_name: string;
  /** This country's words for its two region levels — "State"/"LGA", "Province"/"County". */
  state_label: string;
  area_label: string;
  city_text: string;
  address: string;
  latitude: string | null;
  longitude: string | null;
  phone: string;
  phone_alt: string;
  whatsapp_phone: string;
  opening_hours: string;
  notes: string;
  is_active: boolean;
  /** Derived by the model: "active" | "inactive" | "archived". */
  status: Exclude<StoreStatus, "all">;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface StorePage {
  count: number;
  next: string | null;
  previous: string | null;
  results: StoreRow[];
}

/** One row the backend thinks might be the same shop (`services.DuplicateHint`). */
export interface DuplicateHint {
  kind: "store" | "pickup_location";
  reason: "name" | "address" | "phone";
  label: string;
  detail: string;
  id: number | null;
}

export interface StoreFilters {
  /** ISO country code, e.g. "NG" — the backend matches `country__code` case-insensitively. */
  country?: string;
  state_region?: number;
  area_region?: number;
  store_type?: StoreType;
  status?: StoreStatus;
  q?: string;
  page: number;
}

export function parseStoreFilters(params: URLSearchParams): StoreFilters {
  const filters: StoreFilters = { page: parsePage(params.get("page")) };

  const q = params.get("q")?.trim();
  // Blank is ABSENT, not empty: a GET form submits every field it holds, so an
  // untouched form would otherwise send `?q=&status=` — filters that match everything
  // and a URL that looks filtered.
  if (q) filters.q = q;

  const country = params.get("country")?.trim();
  if (country) filters.country = country.toUpperCase();

  const state = parseId(params.get("state_region"));
  if (state) filters.state_region = state;

  // An area without its state is dropped: the pair is how the form is used, and an
  // orphan area id in a hand-edited URL narrows the list in a way nothing on screen
  // would explain.
  const area = parseId(params.get("area_region"));
  if (area && state) filters.area_region = area;

  const storeType = params.get("store_type")?.trim();
  if (storeType && isStoreType(storeType)) filters.store_type = storeType;

  const status = params.get("status")?.trim();
  // Unrecognised values are DROPPED rather than forwarded — the backend answers 400
  // for `?status=nonsense`, and an error page is the wrong response to a hand-edited
  // URL when "the live directory" is both harmless and obviously what was meant.
  if (status && isStoreStatus(status)) filters.status = status;

  return filters;
}

/** The query string for a set of filters. Omits page 1 — a bare `/find-stores` and
 *  `/find-stores?page=1` are the same screen and should be the same URL. */
export function storesQueryString(filters: StoreFilters): string {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.country) params.set("country", filters.country);
  if (filters.state_region) params.set("state_region", String(filters.state_region));
  if (filters.area_region) params.set("area_region", String(filters.area_region));
  if (filters.store_type) params.set("store_type", filters.store_type);
  if (filters.status) params.set("status", filters.status);
  if (filters.page > 1) params.set("page", String(filters.page));
  return params.toString();
}

function parsePage(raw: string | null): number {
  // Regex rather than a numeric parse: `Number("")` and `Number(" ")` are both 0, and
  // this rejects "1.5" and "abc" identically with no NaN branch. Same rule as
  // lib/products.ts.
  if (!raw || !/^\d+$/.test(raw)) return 1;
  const page = Number(raw);
  return page >= 1 ? page : 1;
}

function parseId(raw: string | null): number | undefined {
  if (!raw || !/^\d+$/.test(raw)) return undefined;
  const id = Number(raw);
  return id >= 1 ? id : undefined;
}
