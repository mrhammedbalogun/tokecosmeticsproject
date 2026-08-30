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
 */
import { CLICK_ID_COOKIE, CONSENT_COOKIE } from "@/lib/consent";

/** The vendors' own cookies, mapped to the short keys the backend stores. */
const PIXEL_COOKIES: Record<string, string> = {
  _fbp: "fbp",
  _fbc: "fbc",
  _ttp: "ttp",
  _scid: "scid",
};

export interface MarketingBlob {
  consent: { marketing: boolean; analytics: boolean; version: number };
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
}: {
  jar: JarLike;
  headers: Headers;
  siteUrl: string;
}): MarketingBlob {
  const consent = parseJson(jar.get(CONSENT_COOKIE)?.value);
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
      marketing: consent.m === 1,
      analytics: consent.a === 1,
      version: typeof consent.v === "number" ? consent.v : 0,
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
