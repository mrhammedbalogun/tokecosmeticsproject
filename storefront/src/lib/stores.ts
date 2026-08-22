/**
 * The store locator's data layer (Plan-42) — the shapes `/api/v1/stores/…` serves and
 * the two server-side readers `/find-stores` renders from.
 *
 * ── THE CASCADE ONLY OFFERS PLACES THAT HOLD A STORE ────────────────────────────────
 *
 * This is `apps.stores.views`' decision, restated here because it shapes every state
 * this UI has: the LGA list for Lagos is the handful of LGAs with a stockist in them,
 * not all 57. So "pick a place, find nothing" is nearly unreachable by clicking — the
 * empty state is for a SHARED LINK whose shop has since been archived. It is still
 * built, and still tested, because links outlive shops.
 *
 * ── SLUGS, NEVER IDS ────────────────────────────────────────────────────────────────
 *
 * `?country=nigeria&state=lagos&area=alimosho`. Legible in the WhatsApp message this
 * page will actually be shared in, and it keeps database ids off a public URL. The
 * backend resolves a country by slug OR ISO code, which is why `code` rides along on a
 * country option — the market cookie holds "NG", and matching it against the offered
 * countries is how a Nigerian reader lands on Nigeria preselected.
 */
import { apiFetch } from "@/lib/api";

export type PlaceLevel = "country" | "state" | "area";

/** One option in one of the three pickers. `store_count` is what the option's
 *  "3 stores" hint renders; `has_children` is what decides whether choosing it opens
 *  another picker or runs the search. */
export interface StorePlace {
  slug: string;
  name: string;
  store_count: number;
  has_children: boolean;
  /** Countries only — the ISO code, and this market's words for its two region levels
   *  ("State"/"Province", "LGA"/"County"). Absent on states and areas. */
  code?: string | null;
  state_label?: string | null;
  area_label?: string | null;
}

export interface PlacesResponse {
  level: PlaceLevel;
  parent: { slug: string; name: string; code: string | null } | null;
  /** The chosen country's word for the level being offered — "LGA" for Nigeria,
   *  "County" for the UK. Absent at country level. */
  label?: string | null;
  items: StorePlace[];
}

export type StoreType = "toke_store" | "distributor";

/** A public store card. Everything it renders and nothing else — the model's staff
 *  `notes` are not in this shape because they are not in the API's. */
export interface StoreCardData {
  id: number;
  name: string;
  store_type: StoreType;
  store_type_label: string;
  address: string;
  city: string;
  area: string;
  state: string;
  country: string;
  country_code: string;
  /** E.164 — the DIALLABLE form, for `tel:`. Never rendered; `phone_display` is. */
  phone: string;
  phone_display: string;
  phone_alt: string;
  phone_alt_display: string;
  whatsapp_url: string;
  opening_hours: string;
  directions_url: string;
}

export interface StorePage {
  count: number;
  next: string | null;
  previous: string | null;
  results: StoreCardData[];
}

/** The query string for a selection, omitting the levels that are not chosen yet.
 *  One builder for the API call, the proxy call and the browser URL, so the three can
 *  never disagree about what "the current selection" is. */
export function selectionQuery(sel: {
  country?: string | null;
  state?: string | null;
  area?: string | null;
}): string {
  const params = new URLSearchParams();
  if (sel.country) params.set("country", sel.country);
  if (sel.state) params.set("state", sel.state);
  if (sel.area) params.set("area", sel.area);
  return params.toString();
}

/**
 * Places at whichever level the arguments describe: no country → the countries,
 * a country → its states, a country and a state → its areas.
 *
 * TOLERANT, BUT HONEST. A failure returns `null` rather than throwing — `/find-stores`
 * is a public page reached from the header menu, and a locator that 500s because a
 * dropdown could not be filled is worse than one that renders its hero and says so.
 * It is `null` and NOT an empty list, though: "the directory is empty" and "Django
 * is down" must not render the same "Nothing here yet", because only one of them
 * deserves a Try-again button, and the page decides which it is showing from this.
 */
export async function getPlaces(
  sel: { country?: string | null; state?: string | null } = {},
  country = "NG",
): Promise<PlacesResponse | null> {
  const qs = selectionQuery(sel);
  try {
    return await apiFetch<PlacesResponse>(`/stores/places/${qs ? `?${qs}` : ""}`, {
      country,
      // Revalidated rather than no-store: the answer changes when a store is added,
      // which is a weekly event at most, and this is on the critical path of a page
      // whose first paint should not wait on Django.
      next: { revalidate: 300 },
    });
  } catch {
    return null;
  }
}

/** Mid-sentence form of a region label: "State" → "state", but "LGA" stays "LGA".
 *  The same rule the admin's `lib/regions.ts` applies, for the same reason — a
 *  lowercased acronym reads as a typo. */
export function lowerLabel(label: string): string {
  return label === label.toUpperCase() ? label : label.toLowerCase();
}

/** "ikotun-egbe" → "Ikotun Egbe": the readable form of a slug nothing resolved, for
 *  the note that says which bookmark went stale. */
export function humaniseSlug(slug: string): string {
  return slug
    .split(/[-_]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/** The stores at a place. Same tolerance as `getPlaces`, same reason. */
export async function getStores(
  sel: { country: string; state?: string | null; area?: string | null },
  country = "NG",
): Promise<StorePage | null> {
  try {
    return await apiFetch<StorePage>(`/stores/?${selectionQuery(sel)}`, {
      country,
      next: { revalidate: 300 },
    });
  } catch {
    return null;
  }
}

/** "Alimosho, Lagos" — the phrase the empty state and the results heading name the
 *  chosen place with. Falls back up the chain when only a state was chosen. */
export function placeLabel(parts: {
  area?: string | null;
  state?: string | null;
  country?: string | null;
}): string {
  return [parts.area, parts.state, parts.country].filter(Boolean).join(", ");
}
