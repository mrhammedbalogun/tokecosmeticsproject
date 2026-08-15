/** Typed fetchers and types for the customer's referral dashboard. Server-side only,
 * same shape as lib/orders.ts: each page owns its own fetch, nothing here caches.
 *
 * Every money field arrives TWICE — the raw decimal string for arithmetic and progress
 * bars, and a `*_display` string the backend formatted with `format_money`. Render the
 * display one. Formatting money in the browser means guessing a currency's symbol and
 * decimal places, and the backend already knows both. */
import { fetchWithAuthOrBounce } from "@/lib/session";

/** One currency's balance. There is deliberately no cross-currency total anywhere —
 * the programme never converts, so a "total earnings" number would be a lie. */
export interface Wallet {
  currency: string;
  symbol: string;
  available: string;
  pending: string;
  paid: string;
  lifetime: string;
  threshold: string;
  available_display: string;
  pending_display: string;
  paid_display: string;
  lifetime_display: string;
  threshold_display: string;
  can_request: boolean;
  remaining_to_threshold: string;
  remaining_to_threshold_display: string;
  /** Set while a payout for this currency is being reviewed or sent — the payout
   * button is off and the customer is told why, rather than being told they have ₦0. */
  open_request_id: number | null;
}

/** ₦200k Club progress. `qualifying_sales` is net SALES driven, not the 10% cut. */
export interface Tier {
  currency: string;
  qualifying_sales: string;
  threshold: string;
  window_days: number;
  is_elite: boolean;
  progress_percent: number;
  qualifying_sales_display: string;
  threshold_display: string;
  /** "The ₦200k Club" — the tier's published NAME, not its threshold formatted as
   * money. Built server-side so it follows the setting if the number ever moves. */
  club_name: string;
}

export interface ReferralOverview {
  code: string;
  is_blocked: boolean;
  terms_accepted_at: string | null;
  terms_version: string;
  current_terms_version: string;
  share_url: string;
  /** The published programme numbers, served as DATA so the page's copy and the code
   * that actually pays commission can never drift apart. Never hardcode "10%" in JSX. */
  commission_percent: string;
  cookie_days: number;
  hold_days: number;
  referred_customers: number;
  wallets: Wallet[];
  tiers: Tier[];
  has_payout_method: boolean;
}

export interface Commission {
  id: number;
  order_number: string;
  placed_at: string;
  status: "pending" | "available" | "paid" | "reversed";
  status_label: string;
  currency: string;
  base_amount: string;
  rate_percent: string;
  amount: string;
  amount_display: string;
  base_amount_display: string;
  /** Null until the order ships — the holding clock starts at dispatch, not payment. */
  matures_at: string | null;
  reversed_reason: string;
  /** "Chidi O." — a referrer learns their link worked, not who the customer is. */
  customer_label: string;
}

export interface Adjustment {
  id: number;
  created_at: string;
  kind: "clawback" | "bonus" | "correction";
  reason: string;
  currency: string;
  /** SIGNED — negative for a clawback. */
  amount: string;
  amount_display: string;
  settled: boolean;
}

export interface CommissionPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: Commission[];
  /** Only populated on page 1 — see the backend view for why. */
  adjustments: Adjustment[];
}

export interface PayoutMethod {
  currency: string;
  bank_name: string;
  account_name: string;
  /** "•••• 6789". The full number is never sent to a browser. */
  account_number_masked: string;
  bank_code: string;
  updated_at: string;
}

export interface Payout {
  id: number;
  created_at: string;
  currency: string;
  amount: string;
  amount_display: string;
  status: "requested" | "approved" | "paid" | "rejected";
  status_label: string;
  paid_at: string | null;
  reference: string;
  customer_message: string;
  bank_name: string;
  account_masked: string;
}

export interface PayoutPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: Payout[];
}

export function getReferralOverview(currentPath: string): Promise<ReferralOverview> {
  return fetchWithAuthOrBounce<ReferralOverview>("/me/referrals/", currentPath, {
    cache: "no-store",
  });
}

export function getCommissions(page: number, currentPath: string): Promise<CommissionPage> {
  return fetchWithAuthOrBounce<CommissionPage>(
    `/me/referrals/commissions/?page=${page}`, currentPath, { cache: "no-store" },
  );
}

export function getPayouts(currentPath: string): Promise<PayoutPage> {
  return fetchWithAuthOrBounce<PayoutPage>("/me/referrals/payouts/", currentPath, {
    cache: "no-store",
  });
}

export function getPayoutMethods(currentPath: string): Promise<PayoutMethod[]> {
  return fetchWithAuthOrBounce<PayoutMethod[]>("/me/referrals/payout-methods/", currentPath, {
    cache: "no-store",
  });
}

/** Short date for the activity table. `undefined` locale so it follows the runtime's,
 * matching `formatOrderDate` in lib/orders.ts. */
export function formatReferralDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    day: "numeric", month: "short", year: "numeric",
  });
}

/**
 * "Ready in 41 days" — how the holding period is explained on a pending row.
 *
 * Returns a sentence rather than a date on purpose: a referrer looking at "17 Oct 2026"
 * has to do arithmetic to know whether that is soon. Falls back to explaining WHY there
 * is no date yet, because "—" next to a commission is the thing that generates support
 * emails: the clock has not started because the order has not shipped.
 */
export function holdingLabel(commission: Commission, holdDays: number): string {
  if (commission.status !== "pending") return "";
  if (!commission.matures_at) {
    return `Ready ${holdDays} days after your friend's order ships`;
  }
  const days = Math.ceil(
    (new Date(commission.matures_at).getTime() - Date.now()) / 86_400_000,
  );
  if (days <= 0) return "Releasing shortly";
  if (days === 1) return "Ready tomorrow";
  return `Ready in ${days} days`;
}
