/** The blob the checkout BFF snapshots onto an order. */
import { describe, expect, it } from "vitest";
import { buildMarketingBlob } from "@/lib/tracking/attribution";
import type { MarketingConfig } from "@/lib/marketing";

function jarOf(cookies: Record<string, string>) {
  return { get: (name: string) => (name in cookies ? { value: cookies[name] } : undefined) };
}

const SITE = "https://tokecosmetics.com";

/** A shop that is measuring, asking first in GB and running opt-out everywhere else —
 * which is production's actual policy. `consent_version: 2` so a stored answer given
 * against v1 can be told apart from a current one. */
const CONFIG: MarketingConfig = {
  tracking_enabled: true,
  consent_version: 2,
  consent_required_countries: ["GB"],
  channels: [{ code: "meta", pixel_id: "123", secondary_id: "" }],
};

/** `country` defaults to NG: the opt-out market this shop mostly sells into. */
function blobFor(
  cookies: Record<string, string>,
  { country = "NG", config = CONFIG, headers = new Headers() } = {},
) {
  return buildMarketingBlob({ jar: jarOf(cookies), headers, siteUrl: SITE, country, config });
}

describe("consent", () => {
  it("records what the visitor actually chose", () => {
    const blob = blobFor({ tc_consent: JSON.stringify({ v: 2, a: 1, m: 1 }) });
    expect(blob.consent).toEqual({
      marketing: true, analytics: true, version: 2, status: "explicit",
    });
  });

  it("records a refusal as a refusal, not as a missing answer", () => {
    // The order still gets a row. "We deliberately did not report this" is a different
    // fact from "nobody looked", and the difference is what answers a gap in an ad
    // account months later.
    const blob = blobFor({ tc_consent: JSON.stringify({ v: 2, a: 0, m: 0 }) });
    expect(blob.consent).toEqual({
      marketing: false, analytics: false, version: 2, status: "explicit",
    });
  });

  // ── THE 2026-09-18 BUG ─────────────────────────────────────────────────────────────
  //
  // 130 of 352 production orders recorded a refusal; 108 of them carried `_fbp`/`_ttp`,
  // which only exist when the marketing scripts ran. They were opt-out visitors who had
  // simply never touched the banner, and every one of their conversions was dropped by
  // `_skip_reason` as `no_marketing_consent`.
  it("does not read a missing cookie as a refusal in an opt-out market", () => {
    const blob = blobFor({});
    expect(blob.consent).toEqual({
      marketing: true, analytics: true, version: 2, status: "implied",
    });
  });

  it("still denies by default where consent must be asked for first", () => {
    const blob = blobFor({}, { country: "GB" });
    expect(blob.consent).toEqual({
      marketing: false, analytics: false, version: 2, status: "implied",
    });
  });

  it("treats an unknown country as consent-required, not as opt-out", () => {
    // A UK visitor behind a VPN looks exactly like this. `consentRequired` guesses the
    // polite way round, and this path must not quietly guess the other way.
    expect(blobFor({}, { country: "" }).consent.marketing).toBe(false);
  });

  it("re-derives the default when the stored answer is against an older version", () => {
    // The visitor agreed to the channels we listed then, not to a list we extended
    // afterwards. `ConsentProvider` is re-asking this person; a stale `m: 0` must not be
    // reported here as a current explicit refusal.
    const blob = blobFor({ tc_consent: JSON.stringify({ v: 1, a: 0, m: 0 }) });
    expect(blob.consent).toEqual({
      marketing: true, analytics: true, version: 2, status: "implied",
    });
  });

  // ── FAIL CLOSED ───────────────────────────────────────────────────────────────────
  //
  // `NO_TRACKING` carries an EMPTY `consent_required_countries`, and an empty list makes
  // `consentRequired` false for every country on earth. Deriving a default from it
  // unguarded would hand every visitor an implied grant during an API outage.
  it("records a refusal when the config could not be read", () => {
    const blob = blobFor({}, {
      config: { tracking_enabled: false, consent_version: 0,
                consent_required_countries: [], channels: [] },
    });
    expect(blob.consent.marketing).toBe(false);
    expect(blob.consent.analytics).toBe(false);
  });

  it("records a refusal when tracking is on but no channel is configured", () => {
    // The same gate ConsentProvider applies: a shop with no channel loads no pixel and
    // sends no event, so there is nothing to have consented to.
    const blob = blobFor({ tc_consent: JSON.stringify({ v: 2, a: 1, m: 1 }) }, {
      config: { ...CONFIG, channels: [] },
    });
    expect(blob.consent.marketing).toBe(false);
  });
});

describe("the vendors' cookies", () => {
  it("collects each pixel's own first-party cookie under our short key", () => {
    const blob = buildMarketingBlob({
      config: CONFIG,
      country: "NG",
      jar: jarOf({
        _fbp: "fb.1.1700000000.111",
        _fbc: "fb.1.1700000000.CLICK",
        _ttp: "ttp-abc",
        _scid: "scid-abc",
      }),
      headers: new Headers(),
      siteUrl: SITE,
    });
    expect(blob.pixel_cookies).toEqual({
      fbp: "fb.1.1700000000.111",
      fbc: "fb.1.1700000000.CLICK",
      ttp: "ttp-abc",
      scid: "scid-abc",
    });
  });

  it("extracts GA4's client id rather than forwarding the raw _ga cookie", () => {
    // GA4 accepts the raw value and treats every purchase as a different new user —
    // a silent failure that looks like a spike in first-time buyers.
    const blob = buildMarketingBlob({
      config: CONFIG,
      country: "NG",
      jar: jarOf({ _ga: "GA1.1.1234567890.1234567890" }),
      headers: new Headers(),
      siteUrl: SITE,
    });
    expect(blob.pixel_cookies.ga).toBe("1234567890.1234567890");
  });

  it("omits a malformed _ga instead of sending nonsense", () => {
    const blob = buildMarketingBlob({
      config: CONFIG,
      country: "NG",
      jar: jarOf({ _ga: "GA1.1" }),
      headers: new Headers(),
      siteUrl: SITE,
    });
    expect(blob.pixel_cookies.ga).toBeUndefined();
  });
});

describe("the client's own address", () => {
  it("prefers x-real-ip, which needs no splitting", () => {
    const blob = buildMarketingBlob({
      config: CONFIG,
      country: "NG",
      jar: jarOf({}),
      headers: new Headers({ "x-real-ip": "102.89.1.1", "user-agent": "Mozilla/5.0" }),
      siteUrl: SITE,
    });
    expect(blob.client_ip).toBe("102.89.1.1");
    expect(blob.client_user_agent).toBe("Mozilla/5.0");
  });

  it("takes the FIRST entry of x-forwarded-for — the client, not a proxy", () => {
    const blob = buildMarketingBlob({
      config: CONFIG,
      country: "NG",
      jar: jarOf({}),
      headers: new Headers({ "x-forwarded-for": "102.89.1.1, 10.0.0.1, 10.0.0.2" }),
      siteUrl: SITE,
    });
    expect(blob.client_ip).toBe("102.89.1.1");
  });
});

describe("click ids", () => {
  it("forwards what the proxy stored", () => {
    const blob = buildMarketingBlob({
      config: CONFIG,
      country: "NG",
      jar: jarOf({ tc_clk: JSON.stringify({ fbclid: "FB1", ts: 1700000000 }) }),
      headers: new Headers(),
      siteUrl: SITE,
    });
    expect(blob.click_ids).toEqual({ fbclid: "FB1", ts: 1700000000 });
  });

  it("is empty, never broken, when the cookie is junk", () => {
    const blob = buildMarketingBlob({
      config: CONFIG,
      country: "NG",
      jar: jarOf({ tc_clk: "not json" }),
      headers: new Headers(),
      siteUrl: SITE,
    });
    expect(blob.click_ids).toEqual({});
  });
});
