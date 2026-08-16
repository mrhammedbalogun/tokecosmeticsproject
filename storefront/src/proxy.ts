import { NextResponse, type NextRequest } from "next/server";
import { REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { GEO_COUNTRY_HEADER } from "@/lib/geo";
import {
  REFERRAL_COOKIE,
  REFERRAL_COOKIE_MAX_AGE,
  REFERRAL_PARAM,
  normalizeReferralCode,
} from "@/lib/referral";

// Shared with the POST /api/country route handler so the seeded default and an explicit user
// choice are stored with identical flags. `country` is deliberately NOT httpOnly — client UI
// reads it. `secure` in production only (so http://localhost still receives it in dev).
const COUNTRY_COOKIE_OPTIONS = {
  httpOnly: false,
  sameSite: "lax" as const,
  path: "/",
  maxAge: 60 * 60 * 24 * 365,
  secure: process.env.NODE_ENV === "production",
};

// MUST stay in sync with the backend's active markets (GET /meta/countries/) and the list in
// CurrencyWelcomeModal. Inlined (not imported from lib/country) because the proxy must stay
// dependency-free — see the note below about CDN-edge deployment.
const MARKET_CODES = ["NG", "GB", "US", "CA", "ZZ"];
const REST_OF_WORLD = "ZZ";

// httpOnly, unlike the country cookie: no page JavaScript has any business reading or
// writing the attribution, and making it unreadable means the only path from a URL to a
// commission runs through this file and then straight to the server-side checkout call.
const REFERRAL_COOKIE_OPTIONS = {
  httpOnly: true,
  sameSite: "lax" as const,
  path: "/",
  maxAge: REFERRAL_COOKIE_MAX_AGE,
  secure: process.env.NODE_ENV === "production",
};

/** Mirror of lib/country's normalizeCountry: geo absent -> NG default; a real market ->
 * itself; any other country -> ZZ (international, USD). */
function marketForGeo(geo: string): string {
  if (!geo) return DEFAULT_COUNTRY;
  const upper = geo.toUpperCase();
  return MARKET_CODES.includes(upper) ? upper : REST_OF_WORLD;
}

// Next.js 16 renamed the `middleware` file convention to `proxy` (Node.js runtime only).
// See node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/proxy.md.
//
// Only ONE proxy file may exist, so everything that must run before a route renders lives
// here. Keep it dependency-free: the docs warn it may be deployed to the CDN edge, separate
// from render code, so it must not import shared modules with real behaviour (cookie-name
// constants only — never lib/session.ts).
//
// The /account check below is PRESENCE THEATRE, deliberately. It cannot verify a token, so
// it is not authorization: it only avoids rendering eight dynamic pages for an obviously
// logged-out visitor and attaches a correct ?next= on a direct URL hit. The real gate is
// each account page's own data fetch (see lib/session.ts requireAuth).
export async function proxy(req: NextRequest) {
  const existing = req.cookies.get(COUNTRY_COOKIE)?.value;

  // Trust ONLY the platform-injected geo header (Vercel sets x-vercel-ip-country in prod).
  // We overwrite the forwarded x-geo-country with it, so a client-spoofed x-geo-country on
  // the incoming request can never reach Server Components. Absent locally -> "" -> the
  // welcome popup stays hidden. NEVER redirect — geo only picks a starting market.
  const geo = req.headers.get("x-vercel-ip-country") ?? "";
  const requestHeaders = new Headers(req.headers);
  requestHeaders.set(GEO_COUNTRY_HEADER, geo);

  // Seed a country cookie on the very first request from the visitor's geo (a Canadian
  // starts in CAD, unknown countries in ZZ/USD, no geo -> NG) so first impressions are
  // priced in their currency. Only when absent — an existing choice is never overwritten.
  // The seed is ALSO injected into the forwarded request's cookie header: the response
  // Set-Cookie only reaches the browser after this render, so without the injection every
  // cookies() reader would fall back to NG for the very first paint.
  const seed = existing ? null : marketForGeo(geo);
  if (seed) {
    const cookieHeader = req.headers.get("cookie");
    requestHeaders.set(
      "cookie",
      cookieHeader ? `${cookieHeader}; ${COUNTRY_COOKIE}=${seed}` : `${COUNTRY_COOKIE}=${seed}`,
    );
  }

  // Referral attribution. A visit carrying ?ref=CODE on ANY route starts (or restarts)
  // that referrer's 30-day window — the link a referrer shares is usually the homepage,
  // but a product link with ?ref= appended has to work identically or the first thing
  // they try will silently earn nothing.
  //
  // The URL is deliberately NOT rewritten to strip the parameter. A redirect here would
  // cost every referred landing an extra round-trip, and it would break any UTM
  // parameters the referrer is running alongside it in an ad tool. `?ref=` in the
  // address bar is harmless; the pages ignore it.
  // Two ways in, one mechanism. `?ref=CODE` on any URL is what the share buttons emit;
  // `/r/CODE` is the short form a referrer can say out loud or print. The short link
  // resolves here rather than as a page so it costs no render and cannot 404 — ANY
  // two-segment /r/* path redirects to the homepage, valid code or not, because the
  // excluded characters (0/1/I/O) are exactly the ones people mistype from a printed
  // card, and a mistyped card must land on the shop rather than an error page. The
  // cookie is only set when the code survives normalisation.
  const rawShortCode = shortLinkCode(req.nextUrl.pathname);
  const isShortLink = rawShortCode !== "";
  const referral = normalizeReferralCode(rawShortCode)
    || normalizeReferralCode(req.nextUrl.searchParams.get(REFERRAL_PARAM));

  const res = isShortLink
    ? NextResponse.redirect(new URL("/", req.nextUrl))
    : isGatedAccountPath(req.nextUrl.pathname) && !req.cookies.get(REFRESH_COOKIE)
      ? NextResponse.redirect(loginUrl(req))
      : NextResponse.next({ request: { headers: requestHeaders } });

  // Set on the redirect too: a first-time visitor deep-linking into /account must not come
  // back from login without a market, or they'd be shown the wrong currency.
  if (seed) {
    res.cookies.set(COUNTRY_COOKIE, seed, COUNTRY_COOKIE_OPTIONS);
  }
  // LAST-CLICK WINS, with one referee. A valid competing code overwrites the stored one
  // (that IS the rule — see lib/referral.ts) and any set refreshes the 30 days. But
  // "well-formed" is not "real": before the existence check, `?ref=BOGUSQ9X2` — pattern-
  // valid, never minted, craftable by anyone — clobbered a genuine referrer's stored
  // attribution with garbage. The typed-code path (/api/referral) always refused that;
  // this brings the link path level. The lookup runs ONLY in the contested case (a
  // stored code, and a different one arriving), so the common paths — first click, and
  // the same link re-clicked — stay zero-round-trip on a hook that runs every
  // navigation. On lookup failure the STORED code survives: an unverifiable new claim
  // must not destroy a verified old one.
  if (referral) {
    const stored = req.cookies.get(REFERRAL_COOKIE)?.value ?? "";
    const contested = stored !== "" && stored !== referral;
    if (!contested || (await referralCodeExists(referral))) {
      res.cookies.set(REFERRAL_COOKIE, referral, REFERRAL_COOKIE_OPTIONS);
    }
  }

  return res;
}

/**
 * "Was this code ever minted?" — asked of the backend's public lookup, the same one
 * /api/referral validates typed codes against. Inlined fetch rather than lib/api's
 * client because the proxy must stay dependency-free (see the note above), and
 * anonymous on purpose: the only question here is existence, and the lookup already
 * refuses to distinguish blocked from nonexistent. False on ANY failure — the caller
 * treats false as "keep the stored attribution", which is the conservative direction.
 */
async function referralCodeExists(code: string): Promise<boolean> {
  const base = process.env.API_URL ?? "http://localhost:8000";
  try {
    const r = await fetch(
      `${base}/api/v1/referrals/lookup/?code=${encodeURIComponent(code)}`,
      { cache: "no-store", signal: AbortSignal.timeout(1500) },
    );
    if (!r.ok) return false;
    const body = (await r.json()) as { valid?: boolean };
    return body.valid === true;
  } catch {
    return false;
  }
}

/**
 * The code in `/r/AMINA7K3P`, or "" for any other path.
 *
 * Exactly two segments, so `/r/CODE/anything` is not a referral link — the returned
 * value is normalised by the caller anyway, but matching loosely here would send a
 * visitor from a real deep link to the homepage for no reason.
 */
function shortLinkCode(pathname: string): string {
  const segments = pathname.split("/").filter(Boolean);
  return segments.length === 2 && segments[0] === "r" ? segments[1] : "";
}

/** Exact segment match — `/accountants-special` is not an account route. */
function isGatedAccountPath(pathname: string): boolean {
  return pathname === "/account" || pathname.startsWith("/account/");
}

function loginUrl(req: NextRequest): URL {
  const url = new URL("/login", req.nextUrl);
  // Only the path — never the full URL. Round-tripping an absolute URL through `next`
  // is how open-redirects start; `safeNext` on the reading side rejects those anyway.
  url.searchParams.set("next", req.nextUrl.pathname + req.nextUrl.search);
  return url;
}

export const config = {
  // Run on every route except static assets, the image optimizer, favicon, /logos, and /api.
  // Exclusions are anchored (trailing slash / exact filename) so prefix collisions such as a
  // future /api-docs or /logos-landing still get the proxy.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|logos/|api/).*)"],
};
