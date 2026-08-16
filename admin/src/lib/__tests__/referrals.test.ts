import { describe, it, expect } from "vitest";
import {
  PAYOUT_AGING_DAYS,
  isAging,
  parsePayoutFilters,
  payoutAmount,
  payoutsQueryString,
  type PayoutRow,
} from "@/lib/referrals";

function row(overrides: Partial<PayoutRow> = {}): PayoutRow {
  return {
    id: 1,
    created_at: "2026-08-01T09:00:00Z",
    status: "requested",
    currency: "NGN",
    amount: "30000.00",
    // Zero by ruling — the card hides the split unless a deduction was actually taken.
    wht_rate_percent: "0.00",
    wht_amount: "0.00",
    net_amount: "30000.00",
    referrer_id: 7,
    referrer_name: "Amina Okoro",
    referrer_email: "amina@example.com",
    referrer_toke_id: "TK-000123",
    referrer_is_blocked: false,
    bank_name: "GTBank",
    account_name: "AMINA OKORO",
    account_number: "0123456789",
    bank_code: "058",
    commission_count: 3,
    flags: [],
    days_open: 2,
    decided_at: null,
    decided_by_email: "",
    paid_at: null,
    reference: "",
    admin_note: "",
    customer_message: "",
    ...overrides,
  };
}

describe("payout filters", () => {
  it("drops a status the API does not know", () => {
    // An unrecognised status passed upstream returns an empty list, which on screen is
    // indistinguishable from "there are no payouts" — a filter typo would read as good
    // news. Dropping it shows the unfiltered queue instead.
    expect(parsePayoutFilters({ status: "settled" }).status).toBe("");
    expect(parsePayoutFilters({ status: "paid" }).status).toBe("paid");
  });

  it("falls back to page 1 for junk page numbers", () => {
    expect(parsePayoutFilters({ page: "0" }).page).toBe(1);
    expect(parsePayoutFilters({ page: "-3" }).page).toBe(1);
    expect(parsePayoutFilters({ page: "abc" }).page).toBe(1);
    expect(parsePayoutFilters({ page: "4" }).page).toBe(4);
  });

  it("takes the first value when a param is repeated", () => {
    expect(parsePayoutFilters({ search: ["amina@example.com", "x"] }).search).toBe(
      "amina@example.com",
    );
  });

  it("omits page 1 from the query string so the canonical URL stays clean", () => {
    expect(payoutsQueryString({ page: 1 })).toBe("");
    expect(payoutsQueryString({ page: 2, status: "requested" })).toBe(
      "?page=2&status=requested",
    );
  });
});

describe("aging", () => {
  it("marks a request late only once it passes the same threshold the sweep alerts on", () => {
    // Mirrors PAYOUT_AGING_DAYS in backend/apps/referrals/tasks.py. If the two drift, the
    // screen and the Sentry alert disagree about what "late" means.
    expect(isAging(row({ days_open: PAYOUT_AGING_DAYS - 1 }))).toBe(false);
    expect(isAging(row({ days_open: PAYOUT_AGING_DAYS }))).toBe(true);
  });

  it("never calls a decided request late", () => {
    // `days_open` is null once decided. A paid payout that took three weeks is history,
    // not a problem, and flagging it would train someone to ignore the colour.
    expect(isAging(row({ status: "paid", days_open: null }))).toBe(false);
  });
});

describe("payoutAmount", () => {
  it("shows the currency the commission was earned in, never a converted one", () => {
    // The programme never converts between currencies — a GBP balance is paid in GBP or
    // not at all — so the code is printed rather than a symbol chosen for the viewer.
    expect(payoutAmount(row({ currency: "NGN", amount: "30000.00" }))).toBe("NGN 30,000.00");
    expect(payoutAmount(row({ currency: "GBP", amount: "42.50" }))).toBe("GBP 42.50");
  });
});

describe("REFERRAL_PAGE_SIZE (2026-08-15 review)", () => {
  it("is 20, matching the backend's ReferralPagination — not the global 24", async () => {
    // The queue pages divided page.count by the global PAGE_SIZE (24) while the
    // referral endpoints serve 20 a page: at 45 rows the pager offered 2 pages and
    // rows 41-45 — real payout requests — were unreachable except by hand-typed URL.
    const { REFERRAL_PAGE_SIZE } = await import("../referrals");
    const { pageCount } = await import("../pagination");
    expect(REFERRAL_PAGE_SIZE).toBe(20);
    expect(pageCount(45, REFERRAL_PAGE_SIZE)).toBe(3);
    expect(pageCount(40, REFERRAL_PAGE_SIZE)).toBe(2);
    expect(pageCount(0, REFERRAL_PAGE_SIZE)).toBe(1);
  });
});
