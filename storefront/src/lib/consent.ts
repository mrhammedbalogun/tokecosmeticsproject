/**
 * Tracking consent: the cookie, the regional rule, and the vocabulary (Plan-44).
 *
 * Constants and PURE FUNCTIONS only. `proxy.ts` imports from here, and the proxy must
 * stay dependency-free — it may be deployed to the CDN edge, separate from render code,
 * so it may only import modules with no behaviour of their own. This file is exactly
 * that kind of module, the same shape as `lib/referral.ts` next door.
 *
 * ── TWO REGIMES, ONE COOKIE ─────────────────────────────────────────────────────────
 *
 * The shop sells into Nigeria, the UK, the US, Canada and rest-of-world, and a single
 * global rule is either illegal in the UK or needlessly destroys Nigerian data:
 *
 *   CONSENT REQUIRED (GB + EEA by default)  Nothing is stored and no pixel loads until
 *                                           the visitor chooses. UK GDPR + PECR require
 *                                           consent BEFORE a non-essential cookie is set.
 *   EVERYWHERE ELSE                         The banner is shown and withdrawal works,
 *                                           but tracking runs until it is declined.
 *
 * The country list is served by the backend (`/marketing/config/`), not frozen here, so
 * adding Nigeria under the NDPA 2023 is an admin edit rather than a deploy. That is a
 * decision Hammed has not made yet and should not need a release to make.
 *
 * ── WHY THIS COOKIE IS NOT httpOnly ─────────────────────────────────────────────────
 *
 * `tc_ref` next door IS httpOnly, because it decides who gets paid a commission and page
 * JavaScript has no business naming that. This one is the opposite: its whole purpose is
 * to be read by page JavaScript, which is what decides whether a pixel script is
 * injected at all. A consent state the browser cannot read is a consent state the
 * browser cannot honour.
 */

/** The cookie the visitor's choice lives in. */
export const CONSENT_COOKIE = "tc_consent";

/**
 * Six months. The ICO's guidance is that consent should not be treated as indefinite,
 * and six months is the common reading of "refreshed periodically" — long enough that a
 * regular customer is not nagged, short enough that a choice made once is not held
 * against someone for years.
 */
export const CONSENT_MAX_AGE = 60 * 60 * 24 * 182;

/** The click ids captured off a landing URL, so a server-side event can attribute the
 * ad click even when the vendor's own pixel never ran (an ad blocker, a slow consent).
 *
 * NOT httpOnly, unlike `tc_ref`: it is written from the browser the moment consent is
 * granted, on the same page load that the proxy could not write it. It carries ad click
 * identifiers and nothing else — no session, no identity, no money. */
export const CLICK_ID_COOKIE = "tc_clk";

/** 90 days: past every one of the four platforms' click-attribution windows. */
export const CLICK_ID_MAX_AGE = 60 * 60 * 24 * 90;

/** The query parameters each platform appends to an ad's destination URL. */
export const CLICK_ID_PARAMS: Record<string, string> = {
  fbclid: "fbclid",   // Meta — Facebook and Instagram
  ttclid: "ttclid",   // TikTok
  ScCid: "sccid",     // Snapchat (capitalised in their URLs; lowercased in our store)
  gclid: "gclid",     // Google Ads
  wbraid: "wbraid",   // Google Ads, web-to-app
  gbraid: "gbraid",   // Google Ads, app-to-web
};

export type ConsentCategory = "analytics" | "marketing";

export interface ConsentState {
  /** Which `MarketingSettings.consent_version` this answer was given against. A new
   * channel bumps the version and re-asks: the visitor agreed to the pixels we listed,
   * not to a list we extended afterwards. */
  version: number;
  analytics: boolean;
  marketing: boolean;
  /** "explicit" — the visitor chose. "implied" — no choice yet, in a region where the
   * regime is opt-out. Nothing outside this module should treat the two as the same:
   * the banner is shown for "implied" and hidden for "explicit". */
  status: "explicit" | "implied";
}

export const DENIED: ConsentState = {
  version: 0, analytics: false, marketing: false, status: "implied",
};

/** Whether this visitor's country requires consent BEFORE anything is stored. */
export function consentRequired(country: string, requiredCountries: string[]): boolean {
  if (!country) {
    // No geo signal. Treat as consent-required: guessing "opt-out" for an unknown
    // visitor is the guess that can be unlawful, and guessing "ask first" is only ever
    // more polite. This is also what a UK visitor behind a VPN looks like.
    return true;
  }
  return requiredCountries.includes(country.toUpperCase());
}

/**
 * The state to assume before the visitor has answered.
 *
 * Consent-required regions start fully denied. Everywhere else starts granted but
 * `implied`, which is what keeps the banner on screen — an implied state is not a
 * choice, it is the absence of one.
 */
export function defaultConsent(
  country: string,
  requiredCountries: string[],
  version: number,
): ConsentState {
  const mustAsk = consentRequired(country, requiredCountries);
  return {
    version,
    analytics: !mustAsk,
    marketing: !mustAsk,
    status: "implied",
  };
}

/** Serialise for the cookie. Short keys because this rides on every request. */
export function encodeConsent(state: ConsentState): string {
  return JSON.stringify({
    v: state.version,
    a: state.analytics ? 1 : 0,
    m: state.marketing ? 1 : 0,
  });
}

/**
 * Read a stored choice, or null when there is none to read.
 *
 * Returns null — never a default — for anything malformed, a cookie from an older
 * format, or a choice given against an OLDER consent version. All three mean "this
 * visitor has not answered the question we are currently asking", and the caller's
 * `defaultConsent` is the right answer to that.
 */
export function decodeConsent(raw: string | undefined | null, currentVersion: number): ConsentState | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(decodeURIComponent(raw));
    if (typeof parsed !== "object" || parsed === null) return null;
    const version = Number(parsed.v);
    if (!Number.isFinite(version) || version < currentVersion) return null;
    return {
      version,
      analytics: parsed.a === 1,
      marketing: parsed.m === 1,
      status: "explicit",
    };
  } catch {
    return null;
  }
}

/**
 * "Does the stored cookie already grant marketing?" — the ONE question `proxy.ts` asks.
 *
 * Deliberately version-blind, unlike `decodeConsent`. The proxy has no idea what the
 * current consent version is (it would need a network call on every navigation to learn
 * it), and it does not need to: a visitor who granted marketing against version 1 has
 * granted marketing. If the version has since moved, the provider re-asks on render and
 * a refusal clears the cookie this permitted. The worst case is one click id stored for
 * the seconds between the landing and the answer, for a visitor who had previously said
 * yes — which is not the case PECR is about.
 */
export function marketingGrantedInCookie(raw: string | undefined | null): boolean {
  if (!raw) return false;
  try {
    return JSON.parse(decodeURIComponent(raw)).m === 1;
  } catch {
    return false;
  }
}

/** May we store and send this category? */
export function allows(state: ConsentState, category: ConsentCategory): boolean {
  return category === "marketing" ? state.marketing : state.analytics;
}

/**
 * The click ids present in a URL, normalised to the keys the backend stores.
 *
 * `ts` rides along because Meta's `_fbc` value embeds the click TIME, and reconstructing
 * it later without one would date every click to whenever the order happened to be
 * placed. See `apps/marketing/channels/meta.py::build_fbc`.
 *
 * Values are length-capped here as well as on the server: this is written into a cookie
 * that travels on every subsequent request, and a caller-controlled URL parameter is not
 * a place to accept unbounded input.
 */
export function clickIdsFromUrl(params: URLSearchParams, now: number = Date.now()): Record<string, string | number> {
  const found: Record<string, string | number> = {};
  for (const [param, key] of Object.entries(CLICK_ID_PARAMS)) {
    const value = params.get(param);
    if (value) found[key] = value.slice(0, 512);
  }
  if (Object.keys(found).length === 0) return {};
  return { ...found, ts: Math.floor(now / 1000) };
}
