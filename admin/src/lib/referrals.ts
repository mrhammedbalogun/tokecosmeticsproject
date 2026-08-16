/**
 * The payout queue's shapes and the small amount of reasoning the page shares with its
 * components.
 *
 * VOCABULARY NOTE, and it is deliberate: this surface says "payout", never "withdrawal"
 * and never "wallet". A referrer's commission is a trade payable the shop settles by
 * bank transfer — an ordinary supplier payment — and the words used about it should not
 * suggest the shop is holding customer funds, which it never does. See the runbook's
 * "Questions for a Nigerian fintech lawyer" section for the full reasoning.
 */

export const PAYOUT_STATUSES = ["requested", "approved", "paid", "rejected"] as const;
export type PayoutStatus = (typeof PAYOUT_STATUSES)[number];

/** Mirrors `_Page.page_size` in `backend/apps/referrals/views.py` — the referral
 * endpoints page at 20, NOT the global DRF PAGE_SIZE of 24. If the two drift, the pager
 * under the payout queue stops lining up with the pages the API actually serves, and
 * the rows past the phantom last page are real payout requests nobody can reach. */
export const REFERRAL_PAGE_SIZE = 20;

export interface PayoutRow {
  id: number;
  created_at: string;
  status: PayoutStatus;
  currency: string;
  amount: string;
  /** The withholding split. Zero by ruling (backend `REFERRAL_WHT_PERCENT`), so the card
   *  hides it rather than printing "WHT 0.00" on every row — a figure that is always
   *  zero is a figure people stop reading, including on the day it is not. */
  wht_rate_percent: string;
  wht_amount: string;
  /** What the bank actually sends. Equal to `amount` today. */
  net_amount: string;

  referrer_id: number;
  referrer_name: string;
  referrer_email: string;
  referrer_toke_id: string;
  referrer_is_blocked: boolean;

  /** The SNAPSHOT taken when the request was made — not the referrer's current account.
   *  Pay what is here; if it disagrees with their account today, `flags` says so. */
  bank_name: string;
  account_name: string;
  account_number: string;
  bank_code: string;

  commission_count: number;
  flags: string[];
  /** Null once decided — a wait only means something while somebody is still waiting. */
  days_open: number | null;

  decided_at: string | null;
  decided_by_email: string;
  paid_at: string | null;
  reference: string;
  admin_note: string;
  customer_message: string;
}

export interface PayoutPage {
  count: number;
  results: PayoutRow[];
}

export interface PayoutCommission {
  id: number;
  order_number: string;
  order_status: string;
  base_amount: string;
  amount: string;
  rate_percent: string;
  created_at: string;
}

/**
 * How long a request may sit before the queue starts shouting. MIRRORS
 * `PAYOUT_AGING_DAYS` in `backend/apps/referrals/tasks.py`, which logs the same threshold
 * to Sentry — if the two drift, the screen and the alert disagree about what "late" is.
 *
 * Fourteen days rather than seven because payouts are processed by hand once a month: a
 * week of waiting is the normal shape of the process, a fortnight means a cycle was
 * missed.
 */
export const PAYOUT_AGING_DAYS = 14;

export function isAging(row: PayoutRow): boolean {
  return row.days_open !== null && row.days_open >= PAYOUT_AGING_DAYS;
}

/** Money as the queue shows it. The API sends decimal strings and the currency code
 *  separately; nothing here converts between currencies, because the programme never
 *  does — a GBP balance is paid in GBP or not at all. */
/** True when a deduction was actually taken, i.e. when gross and net differ. The card
 *  only shows the split then. */
export function hasWithholding(row: PayoutRow): boolean {
  return Number(row.wht_amount) !== 0;
}

export function payoutAmount(row: PayoutRow): string {
  return `${row.currency} ${Number(row.amount).toLocaleString("en-NG", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export const STATUS_LABEL: Record<PayoutStatus, string> = {
  requested: "Awaiting review",
  approved: "Approved — not yet sent",
  paid: "Paid",
  rejected: "Rejected",
};

export function payoutsQueryString(params: {
  page?: number;
  status?: string;
  search?: string;
}): string {
  const q = new URLSearchParams();
  if (params.page && params.page > 1) q.set("page", String(params.page));
  if (params.status) q.set("status", params.status);
  if (params.search) q.set("search", params.search);
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function parsePayoutFilters(
  searchParams: Record<string, string | string[] | undefined>,
): { page: number; status: string; search: string } {
  const one = (key: string): string => {
    const raw = searchParams[key];
    return (Array.isArray(raw) ? raw[0] : raw) ?? "";
  };
  const page = Number.parseInt(one("page"), 10);
  const status = one("status");
  return {
    page: Number.isFinite(page) && page > 0 ? page : 1,
    // An unrecognised status in the URL is dropped rather than passed upstream, where it
    // would return an empty list that looks like "no payouts" instead of "bad filter".
    status: (PAYOUT_STATUSES as readonly string[]).includes(status) ? status : "",
    search: one("search").trim(),
  };
}


// --- referrers: the abuse and correction surface -------------------------------------

export interface ReferrerBalance {
  currency: string;
  available: string;
  pending: string;
  lifetime: string;
}

export interface ReferrerRow {
  id: number;
  email: string;
  toke_id: string;
  name: string;
  code: string;
  is_blocked: boolean;
  blocked_reason: string;
  joined: string;
  referred_customers: number;
  balances: ReferrerBalance[];
}

export interface ReferrerPage {
  count: number;
  results: ReferrerRow[];
}

export const ADJUSTMENT_KINDS = ["clawback", "bonus", "correction"] as const;
export type AdjustmentKind = (typeof ADJUSTMENT_KINDS)[number];

export const ADJUSTMENT_KIND_LABEL: Record<AdjustmentKind, string> = {
  clawback: "Clawback — refunded after payout",
  bonus: "Bonus / retainer",
  correction: "Manual correction",
};

export interface AdjustmentRow {
  id: number;
  created_at: string;
  currency: string;
  amount: string;
  kind: string;
  reason: string;
  created_by_email: string;
  /** True once a payout has absorbed it. An unsettled row is still moving what the
   *  referrer can request right now, which is a different thing to show. */
  settled: boolean;
}

/** Signed money, with the sign kept visible. A "-" that a reader can miss is the whole
 *  risk of this screen: crediting what you meant to claw back looks identical until
 *  someone reconciles the month. */
export function signedAmount(currency: string, amount: string): string {
  const n = Number(amount);
  const body = Math.abs(n).toLocaleString("en-NG", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${n < 0 ? "−" : "+"}${currency} ${body}`;
}

export function referrersQueryString(params: {
  page?: number;
  search?: string;
  blocked?: string;
}): string {
  const q = new URLSearchParams();
  if (params.page && params.page > 1) q.set("page", String(params.page));
  if (params.search) q.set("search", params.search);
  // Only "true" filters. "false" would hide nobody worth hiding and reads as a bug when
  // the list comes back looking unfiltered.
  if (params.blocked === "true") q.set("is_blocked", "true");
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function parseReferrerFilters(
  searchParams: Record<string, string | string[] | undefined>,
): { page: number; search: string; blocked: string } {
  const one = (key: string): string => {
    const raw = searchParams[key];
    return (Array.isArray(raw) ? raw[0] : raw) ?? "";
  };
  const page = Number.parseInt(one("page"), 10);
  const blocked = one("blocked");
  return {
    page: Number.isFinite(page) && page > 0 ? page : 1,
    search: one("search").trim(),
    blocked: blocked === "true" ? "true" : "",
  };
}
