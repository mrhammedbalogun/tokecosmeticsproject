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

export interface PayoutRow {
  id: number;
  created_at: string;
  status: PayoutStatus;
  currency: string;
  amount: string;

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
