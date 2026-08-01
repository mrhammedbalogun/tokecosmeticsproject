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
  gateway: string;
  is_active: boolean;
  sort_order: number;
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
