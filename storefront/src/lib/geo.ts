import { DEFAULT_COUNTRY, normalizeCountry } from "@/lib/country";

/** Request header the proxy uses to forward the platform geo hint to Server Components. */
export const GEO_COUNTRY_HEADER = "x-geo-country";

/**
 * localStorage flag: the visitor has resolved the geo suggestion — dismissed it, accepted
 * it, or made an explicit country choice in the switcher. Once set, the banner never returns.
 */
export const GEO_DISMISS_KEY = "toke-geo-dismissed";

/** True once the geo suggestion is resolved in this browser. Safe server-side (returns false). */
export function isGeoSuggestionDismissed(): boolean {
  return typeof localStorage !== "undefined" && localStorage.getItem(GEO_DISMISS_KEY) === "1";
}

/** Mark the geo suggestion resolved so the banner stays hidden. No-op server-side. */
export function dismissGeoSuggestion(): void {
  if (typeof localStorage !== "undefined") localStorage.setItem(GEO_DISMISS_KEY, "1");
}

/**
 * The proxy now seeds a first-time visitor's country cookie FROM geo, so the popup's job
 * splits into two variants:
 *  - "confirm": geo resolves to the market the visitor is already on — announce the
 *    auto-set currency and offer a way out ("We've set prices to CAD. OK / Change").
 *  - "offer": geo resolves to a DIFFERENT market than the cookie (e.g. a pre-existing
 *    visitor whose cookie was seeded NG before geo-seeding shipped) — ask before switching.
 * Returns null when there is nothing to say: no geo, or geo resolves to the NG home
 * default (the store's own market needs no announcement).
 */
export type GeoWelcome = { kind: "confirm" | "offer"; market: string };

export function welcomeFor(
  currentCountry: string,
  geoCountry: string | undefined,
  validCodes: string[],
): GeoWelcome | null {
  if (!geoCountry) return null;
  // Reuse the backend-mirroring resolver (uppercase -> known market -> ZZ).
  const resolved = normalizeCountry(geoCountry, validCodes);
  if (resolved === DEFAULT_COUNTRY) return null;
  return { kind: resolved === currentCountry ? "confirm" : "offer", market: resolved };
}
