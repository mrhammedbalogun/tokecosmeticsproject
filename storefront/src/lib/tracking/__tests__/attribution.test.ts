/** The blob the checkout BFF snapshots onto an order. */
import { describe, expect, it } from "vitest";
import { buildMarketingBlob } from "@/lib/tracking/attribution";

function jarOf(cookies: Record<string, string>) {
  return { get: (name: string) => (name in cookies ? { value: cookies[name] } : undefined) };
}

const SITE = "https://tokecosmetics.com";

describe("consent", () => {
  it("records what the visitor actually chose", () => {
    const blob = buildMarketingBlob({
      jar: jarOf({ tc_consent: JSON.stringify({ v: 2, a: 1, m: 1 }) }),
      headers: new Headers(),
      siteUrl: SITE,
    });
    expect(blob.consent).toEqual({ marketing: true, analytics: true, version: 2 });
  });

  it("records a refusal as a refusal, not as a missing answer", () => {
    // The order still gets a row. "We deliberately did not report this" is a different
    // fact from "nobody looked", and the difference is what answers a gap in an ad
    // account months later.
    const blob = buildMarketingBlob({
      jar: jarOf({ tc_consent: JSON.stringify({ v: 2, a: 0, m: 0 }) }),
      headers: new Headers(),
      siteUrl: SITE,
    });
    expect(blob.consent).toEqual({ marketing: false, analytics: false, version: 2 });
  });

  it("defaults to no consent when there is no cookie", () => {
    const blob = buildMarketingBlob({ jar: jarOf({}), headers: new Headers(), siteUrl: SITE });
    expect(blob.consent.marketing).toBe(false);
    expect(blob.consent.version).toBe(0);
  });
});

describe("the vendors' cookies", () => {
  it("collects each pixel's own first-party cookie under our short key", () => {
    const blob = buildMarketingBlob({
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
      jar: jarOf({ _ga: "GA1.1.1234567890.1234567890" }),
      headers: new Headers(),
      siteUrl: SITE,
    });
    expect(blob.pixel_cookies.ga).toBe("1234567890.1234567890");
  });

  it("omits a malformed _ga instead of sending nonsense", () => {
    const blob = buildMarketingBlob({
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
      jar: jarOf({}),
      headers: new Headers({ "x-real-ip": "102.89.1.1", "user-agent": "Mozilla/5.0" }),
      siteUrl: SITE,
    });
    expect(blob.client_ip).toBe("102.89.1.1");
    expect(blob.client_user_agent).toBe("Mozilla/5.0");
  });

  it("takes the FIRST entry of x-forwarded-for — the client, not a proxy", () => {
    const blob = buildMarketingBlob({
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
      jar: jarOf({ tc_clk: JSON.stringify({ fbclid: "FB1", ts: 1700000000 }) }),
      headers: new Headers(),
      siteUrl: SITE,
    });
    expect(blob.click_ids).toEqual({ fbclid: "FB1", ts: 1700000000 });
  });

  it("is empty, never broken, when the cookie is junk", () => {
    const blob = buildMarketingBlob({
      jar: jarOf({ tc_clk: "not json" }),
      headers: new Headers(),
      siteUrl: SITE,
    });
    expect(blob.click_ids).toEqual({});
  });
});
