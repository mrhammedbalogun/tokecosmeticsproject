import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/api", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/api")>();
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "@/lib/api";
import {
  PUBLISHED_TERMS,
  getReferralTerms,
  ratePercent,
  thresholdsForMarket,
  type ReferralTerms,
} from "@/lib/referral-terms";

const mockApiFetch = vi.mocked(apiFetch);

const LIVE: ReferralTerms = {
  ...PUBLISHED_TERMS,
  commission_percent: "12.50",
  cookie_days: 45,
  hold_days: 30,
};

// BLOCK BODY, NOT A CONCISE ARROW. `mockReset()` returns the mock itself — a function —
// and vitest treats a function returned from `beforeEach` as a TEARDOWN callback. The
// concise form therefore called `apiFetch()` again after every test; harmless until the
// installed implementation rejects, at which point the teardown orphaned a rejected
// promise and the run failed with the mocked error nobody had asked for.
beforeEach(() => {
  mockApiFetch.mockReset();
});

describe("getReferralTerms", () => {
  it("prefers what the API says, because that is what actually pays", async () => {
    mockApiFetch.mockResolvedValue(LIVE);
    expect(await getReferralTerms()).toEqual(LIVE);
  });

  it("falls back to the published terms rather than failing the page", async () => {
    // /affiliates is a marketing page. A rate lookup that times out must cost the page
    // its freshness, never its content — the same posture the CMS fetchers take.
    mockApiFetch.mockRejectedValue(new Error("upstream is down"));
    expect(await getReferralTerms()).toEqual(PUBLISHED_TERMS);
  });

  it("treats a half-built payload as no payload", async () => {
    // The failure this guards is "undefined%" and "NaN days" rendering on a page about
    // money — worse than showing the values the site was deployed with.
    mockApiFetch.mockResolvedValue({ commission_percent: "10.00" });
    expect(await getReferralTerms()).toEqual(PUBLISHED_TERMS);
  });
});

describe("ratePercent", () => {
  it("drops zeros that carry no information", () => {
    expect(ratePercent("10.00")).toBe("10");
    expect(ratePercent("10")).toBe("10");
  });

  it("keeps a real fraction, because 12.5% is not 12%", () => {
    expect(ratePercent("12.50")).toBe("12.5");
    expect(ratePercent("7.25")).toBe("7.25");
  });
});

describe("thresholdsForMarket", () => {
  const T = PUBLISHED_TERMS.payout_thresholds;

  it("leads with the currency the visitor is shopping in", () => {
    expect(thresholdsForMarket(T, "GBP")[0].currency).toBe("GBP");
    // and still names the rest — a naira minimum shown alone to a UK shopper reads as
    // "£20,000" at a glance.
    expect(thresholdsForMarket(T, "GBP")).toHaveLength(T.length);
  });

  it("leaves the order alone when the market has no configured minimum", () => {
    expect(thresholdsForMarket(T, "JPY")).toEqual(T);
    expect(thresholdsForMarket(T, undefined)).toEqual(T);
  });
});
