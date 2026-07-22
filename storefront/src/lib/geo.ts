import { DEFAULT_COUNTRY, REST_OF_WORLD } from "@/lib/country";

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
  const geo = geoCountry.toUpperCase();
  if (geo === DEFAULT_COUNTRY) return null;
  if (validCodes.includes(geo)) return geo;
  return validCodes.includes(REST_OF_WORLD) ? REST_OF_WORLD : null;
}
