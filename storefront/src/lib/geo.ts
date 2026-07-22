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
 * What (if anything) to SUGGEST to a visitor. Never forces — the caller only shows a
 * dismissable banner. Returns null when there is nothing worth suggesting.
 *  - existing cookie present -> null (their choice is set; leave it alone)
 *  - geo absent -> null
 *  - geo is the NG default -> null (already correct)
 *  - geo is another real market -> that market
 *  - geo is an unknown country -> ZZ (international)
 */
export function suggestionFor(
  existingCookie: string | undefined,
  geoCountry: string | undefined,
  validCodes: string[],
): string | null {
  if (existingCookie) return null;
  if (!geoCountry) return null;
  // Reuse the backend-mirroring resolver (uppercase -> known market -> ZZ). Nothing to
  // suggest when it resolves to the NG default — the visitor is already on the right market.
  const resolved = normalizeCountry(geoCountry, validCodes);
  return resolved === DEFAULT_COUNTRY ? null : resolved;
}
