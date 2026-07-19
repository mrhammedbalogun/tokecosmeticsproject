import { apiFetch } from "@/lib/api";

export const COUNTRY_COOKIE = "country";
export const DEFAULT_COUNTRY = "NG";
/** Backend rest-of-world market code — shown as "International (USD)". */
export const REST_OF_WORLD = "ZZ";

export interface Currency {
  code: string;
  symbol: string;
  decimal_places: number;
}
export interface Market {
  code: string;
  name: string;
  currency: Currency;
  is_default: boolean;
  is_rest_of_world: boolean;
  area_label: string;
}

/** Active markets for the switcher. Cached 1h (ISR) — the list rarely changes. */
export async function getMarkets(): Promise<Market[]> {
  return apiFetch<Market[]>("/meta/countries/", { next: { revalidate: 3600 } });
}

/**
 * Resolve an arbitrary code to a valid market code, mirroring the backend's
 * resolve_country: missing -> NG default; known market -> itself; unknown but
 * present -> ZZ (rest of world).
 */
export function normalizeCountry(
  code: string | undefined | null,
  validCodes: string[],
): string {
  if (!code) return DEFAULT_COUNTRY;
  const upper = code.toUpperCase();
  if (validCodes.includes(upper)) return upper;
  return validCodes.includes(REST_OF_WORLD) ? REST_OF_WORLD : DEFAULT_COUNTRY;
}

/** Group/symbol formatting only — never rounds; the API already fixed the decimals. */
export function formatMoney(amount: string, currencyCode: string, symbol: string): string {
  const n = Number(amount);
  const grouped = new Intl.NumberFormat("en", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
  return `${symbol}${grouped}`;
}

export function labelFor(market: Market): string {
  return market.is_rest_of_world ? "International (USD)" : market.name;
}
