/**
 * The marketing blob the checkout BFF sends with an order (Plan-44).
 *
 * ── WHY THIS IS ASSEMBLED ON THE SERVER ─────────────────────────────────────────────
 *
 * The vendors' first-party cookies (`_fbp`, `_ttp`, `_scid`, `_ga`) are written by their
 * own JavaScript and are readable by ours, but only the BFF route can read them at the
 * same moment it can read the visitor's IP and the consent cookie. Assembling the blob
 * in the browser and posting it would mean trusting the browser for the consent record
 * as well, and the consent record is the one part of this that has to be defensible.
 *
 * It is still not TRUSTED, note — `/api/v1/checkout/` is public and anyone can post to
 * it directly. `apps/marketing/capture.py` documents exactly what a forged blob can and
 * cannot achieve, and enforces the allowlist and the length caps that make it harmless.
 *
 * ── WHY THE CLIENT IP COMES FROM A HEADER ───────────────────────────────────────────
 *
 * Django sees the Vercel function's egress IP, not the customer's, because the request
 * reaches it from this BFF rather than from the browser. Every ad platform's match
 * quality depends on the real one, so it is read from the platform's own forwarding
 * header and passed along explicitly.
 *
 * ── AN ABSENT CONSENT COOKIE IS NOT A REFUSAL ───────────────────────────────────────
 *
 * This file used to read `consent.m === 1` off the cookie and stop there, which meant a
 * missing cookie recorded a decline. In a consent-required region that is right. In an
 * opt-out region it is simply false: `ConsentProvider` grants marketing by default
 * there and loads the pixels, and it never writes a cookie until the visitor actually
 * clicks something. Measured on production 2026-09-18: 130 of 352 orders recorded a
 * refusal, and 108 of those 130 carried `_fbp`/`_ttp`/`_scid` — cookies that only exist
 * when the marketing scripts ran. They were not refusals.
 *
 * So the default is computed here, from the same `defaultConsent` the provider uses and
 * the same country list the backend serves. ONE rule, two readers.
 *
 * ── WHY THE FIX IS NOT "WRITE THE COOKIE ON AN IMPLIED GRANT" ───────────────────────
 *
 * That is the obvious repair and it is a trap. `decodeConsent` reports ANY stored cookie
 * as `status: "explicit"`, and `ConsentProvider` hides the banner on
 * `storedConsent !== null` — so writing a cookie nobody chose would make the banner
 * vanish unclicked. The visitor would lose the prompt AND we would record a choice they
 * never made: worse on both counts. The implied state therefore stays uncookied, and is
 * re-derived wherever it is needed.
 */
import {
  CLICK_ID_COOKIE,
  CONSENT_COOKIE,
  DENIED,
  decodeConsent,
  defaultConsent,
} from "@/lib/consent";
import type { MarketingConfig } from "@/lib/marketing";

/** The vendors' own cookies, mapped to the short keys the backend stores. */
const PIXEL_COOKIES: Record<string, string> = {
  _fbp: "fbp",
  _fbc: "fbc",
  _ttp: "ttp",
  _scid: "scid",
};

export interface MarketingBlob {
  consent: {
    marketing: boolean;
    analytics: boolean;
    version: number;
    /** "explicit" — the visitor chose. "implied" — no choice yet, in a region whose
     * regime is opt-out. The backend stores it verbatim; see the field comment on
     * `marketing.OrderAttribution.consent_status` for why the distinction is kept. */
    status: "explicit" | "implied";
  };
  click_ids: Record<string, string | number>;
  pixel_cookies: Record<string, string>;
  client_ip: string;
  client_user_agent: string;
  event_source_url: string;
}

interface JarLike {
  get(name: string): { value: string } | undefined;
}

/**
 * GA4's `_ga` cookie is `GA1.1.1234567890.1234567890`; the client id is the last two
 * segments. Sending the raw cookie instead is a silent failure — GA4 accepts it and
 * treats every purchase as a different new user.
 */
function gaClientId(raw: string): string {
  const parts = raw.split(".");
  return parts.length >= 4 ? `${parts[2]}.${parts[3]}` : "";
}

function parseJson(raw: string | undefined): Record<string, unknown> {
  if (!raw) return {};
  try {
    const parsed = JSON.parse(decodeURIComponent(raw));
    return typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

export function buildMarketingBlob({
  jar,
  headers,
  siteUrl,
  country,
  config,
}: {
  jar: JarLike;
  headers: Headers;
  siteUrl: string;
  /** The visitor's market, from the same `country` cookie `ConsentProvider` reads. */
  country: string;
  /** The live consent policy. `consent_required_countries` is a backend field precisely
   * so that adding Nigeria under the NDPA is an admin edit — reading it here rather than
   * hardcoding a list is what keeps that promise true on this path too. */
  config: MarketingConfig;
}): MarketingBlob {
  // ── IS THERE ANYTHING TO CONSENT TO? ─────────────────────────────────────────────
  //
  // The SAME gate `ConsentProvider` applies before it will report anything but DENIED,
  // and it has to be here too or the two readers disagree in exactly the case that
  // matters. `NO_TRACKING` — what `getMarketingConfig` returns when the API is
  // unreachable — carries an EMPTY `consent_required_countries`, and an empty list makes
  // `consentRequired` false for every country on earth. Deriving a default from it would
  // hand every visitor an implied grant at the precise moment we know least about them.
  // Fail closed, as the config's own docstring says it intends to.
  const measuring = config.tracking_enabled && config.channels.length > 0;

  // `decodeConsent`, not a bare JSON read: it also returns null for a choice given
  // against an OLDER consent version, which is a visitor the provider is currently
  // re-asking. Treating that stale answer as an explicit choice — which the old
  // `consent.m === 1` did — records a consent to a channel list that has since changed.
  const stored = measuring
    ? decodeConsent(jar.get(CONSENT_COOKIE)?.value, config.consent_version)
    : null;
  const consent = !measuring
    ? DENIED
    : (stored
       ?? defaultConsent(country, config.consent_required_countries, config.consent_version));
  const clickIds = parseJson(jar.get(CLICK_ID_COOKIE)?.value);

  const pixelCookies: Record<string, string> = {};
  for (const [cookieName, key] of Object.entries(PIXEL_COOKIES)) {
    const value = jar.get(cookieName)?.value;
    if (value) pixelCookies[key] = value;
  }
  const ga = jar.get("_ga")?.value;
  if (ga) {
    const clientId = gaClientId(ga);
    if (clientId) pixelCookies.ga = clientId;
  }

  return {
    consent: {
      marketing: consent.marketing,
      analytics: consent.analytics,
      version: consent.version,
      status: consent.status,
    },
    click_ids: clickIds as Record<string, string | number>,
    pixel_cookies: pixelCookies,
    // `x-forwarded-for` is a list; the FIRST entry is the client, the rest are proxies.
    // Vercel sets `x-real-ip` to the same value, which is why it is preferred: it needs
    // no splitting and cannot be confused by an upstream that appends rather than
    // prepends.
    client_ip:
      headers.get("x-real-ip")
      ?? (headers.get("x-forwarded-for") ?? "").split(",")[0].trim(),
    client_user_agent: headers.get("user-agent") ?? "",
    event_source_url: `${siteUrl.replace(/\/$/, "")}/checkout`,
  };
}
