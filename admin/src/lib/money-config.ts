/** Shapes for the money-config and commerce-config admin (Plan-19b). */

export interface BankAccountRow {
  id: number;
  country: string;
  country_name: string;
  currency: string;
  bank_name: string;
  account_name: string;
  account_number: string;
  extra: Record<string, string>;
  instructions: string;
  is_active: boolean;
  updated_at: string;
}

export interface GatewayRow {
  id: number;
  country: string;
  country_name: string;
  /** The market's checkout currency (e.g. "NGN"). */
  country_currency: string;
  gateway: string;
  is_active: boolean;
  sort_order: number;
  /** Whether the storefront menu would actually offer this row right now — `is_active`
   * is intent, and the registry intersects it with keys/account presence per request. */
  configured: boolean;
  missing_settings: string[];
  /** [] means "no restriction" (bank transfer wires work in any currency). */
  supported_currencies: string[];
}

/** One entry per gateway adapter the platform ships, from
 * `GET /admin/payment-gateways/catalog/` — the add-to-market menu. */
export interface GatewayCatalogEntry {
  code: string;
  supported_currencies: string[];
  missing_settings: string[];
  needs: "bank_account" | "api_keys";
}

export interface CouponRow {
  id: number;
  code: string;
  type: "percent" | "fixed" | "free_shipping";
  value: string;
  currency: string | null;
  min_subtotal: string;
  starts_at: string | null;
  ends_at: string | null;
  usage_limit: number | null;
  usage_limit_per_user: number | null;
  is_active: boolean;
  redemption_count: number;
  created_at: string;
}

export interface DeliveryCoverageSummary {
  countries: { code: string; name: string }[];
  /** Capped server-side (first few) — use region_total for the honest count. */
  regions: {
    name: string;
    level: "state" | "city" | "area";
    country_code: string;
    parent_name: string | null;
  }[];
  region_total: number;
}

export interface DeliveryOptionRow {
  id: number;
  name: string;
  kind: "manual" | "carrier";
  carrier_code: string;
  price: string;
  currency: string;
  free_over: string | null;
  quote_required: boolean;
  disclaimer: string;
  min_days: number;
  max_days: number;
  is_active: boolean;
  sort: number;
  country_codes: string[];
  region_count: number;
  region_ids: number[];
  coverage: DeliveryCoverageSummary;
}

/** Markets whose bank transfer is switched on but that have no ACTIVE bank account.
 *
 * This is the failure the backend's own system check warns about (`payments.W002`) —
 * "customers in those countries cannot check out at all" — and its hint says to fix it in
 * Django admin, which is denied at the vhost. Surfacing it here is the fix for the hint as
 * much as for the state. */
export function marketsWithoutAnAccount(
  gateways: GatewayRow[],
  accounts: BankAccountRow[],
): string[] {
  const covered = new Set(accounts.filter((a) => a.is_active).map((a) => a.country));
  return [
    ...new Set(
      gateways
        .filter((g) => g.is_active && g.gateway === "bank_transfer" && !covered.has(g.country))
        .map((g) => g.country),
    ),
  ].sort();
}

/** Why a switched-on gateway row would still not appear at checkout (or null if it
 * would). Mirrors the registry's request-time filter so the toggle cannot lie. */
export function gatewayObstacle(row: GatewayRow): string | null {
  if (row.gateway === "bank_transfer") {
    // configuredness for bank transfer means "an active account exists for the market";
    // the stranded-market alert above the tables says the same thing louder.
    return row.configured ? null : "No active bank account for this market";
  }
  if (row.missing_settings.length > 0) {
    return `Keys not deployed: ${row.missing_settings.join(", ")}`;
  }
  if (
    row.supported_currencies.length > 0 &&
    !row.supported_currencies.includes(row.country_currency)
  ) {
    return `Cannot charge ${row.country_currency}`;
  }
  return null;
}

/** Catalog entries a market could still add (not already offered there). */
export function addableGateways(
  catalog: GatewayCatalogEntry[],
  marketRows: GatewayRow[],
): GatewayCatalogEntry[] {
  const present = new Set(marketRows.map((r) => r.gateway));
  return catalog.filter((entry) => !present.has(entry.code));
}

/** Where a newly added gateway lands: after everything the market already offers. */
export function nextSortOrder(marketRows: GatewayRow[]): number {
  return Math.max(0, ...marketRows.map((r) => r.sort_order)) + 1;
}

/** A coupon that cannot currently discount anything, and why. Display-only. */
export function couponInactiveReason(coupon: CouponRow, now = new Date()): string | null {
  if (!coupon.is_active) return "Switched off";
  if (coupon.starts_at && new Date(coupon.starts_at) > now) return "Starts later";
  if (coupon.ends_at && new Date(coupon.ends_at) < now) return "Expired";
  if (coupon.usage_limit !== null && coupon.redemption_count >= coupon.usage_limit) {
    return "Usage limit reached";
  }
  return null;
}
