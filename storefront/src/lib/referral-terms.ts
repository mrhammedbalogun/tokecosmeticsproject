/**
 * The referral programme's published numbers, for the PUBLIC /affiliates page.
 *
 * ── WHY THIS IS FETCHED AND NOT WRITTEN DOWN ────────────────────────────────────────
 *
 * /affiliates is advertising. "10% of every sale", "30-day window", "60 days", "₦20,000
 * minimum" are commercial promises the shop is bound by, and the only safe place for
 * them is the settings the commission is actually calculated from. `lib/referrals.ts`
 * makes the same argument for the signed-in dashboard; this is the public half of it.
 *
 * `GET /api/v1/referrals/terms/` exists for exactly this. It is anonymous, cached for an
 * hour, and discloses nothing about any person.
 *
 * ── THE FALLBACK IS PINNED FROM THE BACKEND, NOT TRUSTED ────────────────────────────
 *
 * A marketing page must not go blank because an API blinked — the same standing ruling
 * the CMS fetchers follow. So `PUBLISHED_TERMS` below is a last-resort copy of the
 * published values.
 *
 * That copy is the dangerous kind of constant: correct on the day it is written, silently
 * wrong the day somebody changes `REFERRAL_COMMISSION_PERCENT` and never looks here. It
 * is therefore PINNED BY A BACKEND TEST — `apps/referrals/tests/test_public_terms.py::
 * test_the_storefront_fallback_still_matches_these_settings` reads THIS FILE and fails if
 * the two disagree. If you change a number here, that test tells you. If you change one
 * in Django settings, that test tells you too. Do not "fix" it by deleting the assertion.
 */
import { apiFetch } from "@/lib/api";

export interface PayoutThreshold {
  currency: string;
  amount: string;
  amount_display: string;
}

export interface EliteTier {
  currency: string;
  threshold: string;
  threshold_display: string;
  /** "The ₦200k Club" — the published NAME, built by the same backend rule the
   *  customer's own dashboard uses. Never rebuild it here. */
  club_name: string;
  window_days: number;
}

export interface ReferralTerms {
  commission_percent: string;
  cookie_days: number;
  hold_days: number;
  terms_version: string;
  payout_thresholds: PayoutThreshold[];
  elite_tiers: EliteTier[];
}

/** PINNED BY A BACKEND TEST — see the file docstring before editing. */
export const PUBLISHED_TERMS: ReferralTerms = {
  commission_percent: "10.00",
  cookie_days: 30,
  hold_days: 60,
  terms_version: "2026-08-14",
  payout_thresholds: [
    { currency: "CAD", amount: "30.00", amount_display: "CA$30.00" },
    { currency: "GBP", amount: "20.00", amount_display: "£20.00" },
    { currency: "NGN", amount: "20000.00", amount_display: "₦20,000.00" },
    { currency: "USD", amount: "25.00", amount_display: "$25.00" },
  ],
  elite_tiers: [
    {
      currency: "NGN",
      threshold: "200000.00",
      threshold_display: "₦200,000.00",
      club_name: "The ₦200k Club",
      window_days: 90,
    },
  ],
};

/** The live terms, or the published fallback if the API cannot answer.
 *
 * Never throws. A marketing page that 500s because a rate lookup timed out is a worse
 * outcome than a marketing page showing the values it was last deployed with. */
export async function getReferralTerms(): Promise<ReferralTerms> {
  try {
    const terms = await apiFetch<ReferralTerms>("/referrals/terms/", {
      next: { revalidate: 3600, tags: ["referral-terms"] },
    });
    // A malformed payload is treated as no payload. Half the numbers rendering as
    // "undefined%" on a page about money is the failure this guards.
    if (!terms?.commission_percent || !terms?.cookie_days || !terms?.hold_days) {
      return PUBLISHED_TERMS;
    }
    return terms;
  } catch {
    return PUBLISHED_TERMS;
  }
}

/** The percentage as customers say it — "10", not "10.00".
 *
 * A trailing ".00" on a headline reads as a spreadsheet cell; a real fractional rate
 * (12.5%) must survive intact. Trims only zeros that carry no information. */
export function ratePercent(commissionPercent: string): string {
  return commissionPercent.replace(/\.0+$/, "").replace(/(\.\d*[1-9])0+$/, "$1");
}

/**
 * The payout minimums, with the visitor's own market first.
 *
 * A Nigerian threshold shown alone to a shopper browsing in pounds reads as "£20,000"
 * to anybody skimming, so every currency is named — but the one they are actually
 * shopping in leads.
 */
export function thresholdsForMarket(
  thresholds: PayoutThreshold[],
  currency: string | undefined,
): PayoutThreshold[] {
  if (!currency) return thresholds;
  const mine = thresholds.filter((t) => t.currency === currency);
  return mine.length ? [...mine, ...thresholds.filter((t) => t.currency !== currency)] : thresholds;
}
