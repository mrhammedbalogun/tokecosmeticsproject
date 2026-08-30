/**
 * The consent rules. Each of these has a legal consequence if it drifts, and none of
 * them fails visibly in production — a banner that quietly stops asking looks identical
 * to a banner nobody clicked.
 */
import { describe, expect, it } from "vitest";
import {
  clickIdsFromUrl,
  consentRequired,
  decodeConsent,
  defaultConsent,
  encodeConsent,
  marketingGrantedInCookie,
} from "@/lib/consent";

const UK_AND_EEA = ["GB", "IE", "DE", "FR"];

describe("the regional rule", () => {
  it("asks a UK visitor before storing anything", () => {
    expect(consentRequired("GB", UK_AND_EEA)).toBe(true);
    expect(defaultConsent("GB", UK_AND_EEA, 1)).toMatchObject({
      analytics: false, marketing: false, status: "implied",
    });
  });

  it("runs opt-out for a Nigerian visitor, until Hammed adds NG to the list", () => {
    expect(consentRequired("NG", UK_AND_EEA)).toBe(false);
    expect(defaultConsent("NG", UK_AND_EEA, 1)).toMatchObject({
      analytics: true, marketing: true, status: "implied",
    });
    // The list is data, not code: adding NG changes the regime with no deploy.
    expect(consentRequired("NG", [...UK_AND_EEA, "NG"])).toBe(true);
  });

  it("treats an unknown country as consent-required", () => {
    // A UK visitor behind a VPN looks exactly like this. Guessing opt-out is the guess
    // that can be unlawful; guessing ask-first is only ever more polite.
    expect(consentRequired("", UK_AND_EEA)).toBe(true);
  });

  it("is case-insensitive, because a cookie can hold either", () => {
    expect(consentRequired("gb", UK_AND_EEA)).toBe(true);
  });

  it("never reports an unanswered visitor as having chosen", () => {
    // `status` is what keeps the banner on screen. An implied grant is the absence of a
    // choice, not a choice — treating the two as the same is how a shop ends up claiming
    // consent it never collected.
    expect(defaultConsent("NG", UK_AND_EEA, 1).status).toBe("implied");
  });
});

describe("the cookie", () => {
  it("round-trips a choice", () => {
    const state = { version: 3, analytics: true, marketing: false, status: "explicit" as const };
    expect(decodeConsent(encodeConsent(state), 3)).toEqual(state);
  });

  it("re-asks when the consent version has moved on", () => {
    // The visitor agreed to the pixels we listed, not to a list we extended afterwards.
    const old = encodeConsent({ version: 1, analytics: true, marketing: true, status: "explicit" });
    expect(decodeConsent(old, 2)).toBeNull();
    expect(decodeConsent(old, 1)).not.toBeNull();
  });

  it("treats anything malformed as unanswered rather than as consent", () => {
    for (const raw of ["", "not json", "{", "null", "[]", undefined]) {
      expect(decodeConsent(raw, 1)).toBeNull();
    }
  });
});

describe("the proxy's version-blind read", () => {
  it("sees a granted cookie without knowing the current version", () => {
    expect(marketingGrantedInCookie(JSON.stringify({ v: 1, a: 1, m: 1 }))).toBe(true);
    expect(marketingGrantedInCookie(JSON.stringify({ v: 1, a: 1, m: 0 }))).toBe(false);
    expect(marketingGrantedInCookie("garbage")).toBe(false);
    expect(marketingGrantedInCookie(undefined)).toBe(false);
  });
});

describe("click ids", () => {
  it("reads every platform's parameter and normalises Snapchat's capitalisation", () => {
    const params = new URLSearchParams(
      "?fbclid=FB1&ttclid=TT1&ScCid=SC1&gclid=G1&utm_source=ig",
    );
    expect(clickIdsFromUrl(params, 1_700_000_000_000)).toEqual({
      fbclid: "FB1", ttclid: "TT1", sccid: "SC1", gclid: "G1", ts: 1_700_000_000,
    });
  });

  it("stamps the click time in SECONDS, because Meta's _fbc is built from it", () => {
    const { ts } = clickIdsFromUrl(new URLSearchParams("?fbclid=X"), 1_700_000_500_000);
    expect(ts).toBe(1_700_000_500);
  });

  it("returns nothing at all for an ordinary navigation", () => {
    expect(clickIdsFromUrl(new URLSearchParams("?ref=AMINA7K3P"))).toEqual({});
    // And specifically does not invent a timestamp for a visit with no ad click.
    expect(clickIdsFromUrl(new URLSearchParams(""))).toEqual({});
  });

  it("caps a caller-controlled value", () => {
    const long = clickIdsFromUrl(new URLSearchParams(`?fbclid=${"F".repeat(5000)}`));
    expect(String(long.fbclid)).toHaveLength(512);
  });
});
