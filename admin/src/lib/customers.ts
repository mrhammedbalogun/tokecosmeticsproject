/** Customer list types and query building (Plan-18b).
 *
 * NOTE FOR ANYONE ADDING A COLUMN: every field here is personal data, and both endpoints
 * are read-audited on the backend — opening these pages writes an audit row on purpose.
 * "Who looked up this customer" is the question that gets asked after an incident.
 */

export interface CustomerRow {
  toke_id: string;
  email: string;
  name: string;
  first_name: string;
  last_name: string;
  phone: string;
  whatsapp: string;
  is_active: boolean;
  marketing_consent: boolean;
  email_verified_at: string | null;
  deletion_requested_at: string | null;
  date_joined: string;
  last_login: string | null;
  legacy_source: string;
}

export interface CustomerTotal {
  currency: string;
  orders: number;
  lifetime_value: string;
}

export interface CustomerDetail extends CustomerRow {
  addresses: {
    id: number;
    label: string;
    line1: string;
    line2: string;
    landmark: string;
    city: string;
    postcode: string;
    country_code: string;
    is_default_shipping: boolean;
    is_default_billing: boolean;
  }[];
  legacy_identities: { store: string; wp_user_id: number }[];
  totals: CustomerTotal[];
  unclaimed_guest_orders: number;
}

export interface CustomerPage {
  count: number;
  results: CustomerRow[];
}

export interface CustomerFilters {
  search: string;
  legacy_source: string;
  is_active: string;
  page: number;
}

export function parseCustomerFilters(raw: URLSearchParams): CustomerFilters {
  const page = Number(raw.get("page"));
  return {
    search: raw.get("search")?.trim() ?? "",
    legacy_source: raw.get("legacy_source") ?? "",
    is_active: raw.get("is_active") ?? "",
    // isSafeInteger, not isInteger: 1e21 IS an integer to isInteger and would reach the
    // query string in exponent form.
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
  };
}

export function customersQueryString(filters: CustomerFilters, page = filters.page): string {
  const params = new URLSearchParams();
  if (filters.search) params.set("search", filters.search);
  if (filters.legacy_source) params.set("legacy_source", filters.legacy_source);
  if (filters.is_active) params.set("is_active", filters.is_active);
  if (page > 1) params.set("page", String(page));
  return params.toString();
}

/** Which WooCommerce store a migrated customer came from. "" means they signed up here. */
export const LEGACY_SOURCES: Record<string, string> = {
  legacy_ng: "Nigeria (current)",
  legacy_ng_old: "Nigeria (old store)",
  legacy_intl: "International",
};

export function sourceLabel(source: string): string {
  return source ? (LEGACY_SOURCES[source] ?? source) : "Signed up here";
}

/** Money, per currency, never summed across them — the project bans FX mixing and Plan-23
 *  imports four currencies of history. */
export function formatTotal(total: CustomerTotal): string {
  const n = Number(total.lifetime_value);
  const amount = Number.isFinite(n)
    ? n.toLocaleString(undefined, { maximumFractionDigits: 2 })
    : total.lifetime_value;
  return `${total.currency} ${amount}`;
}
