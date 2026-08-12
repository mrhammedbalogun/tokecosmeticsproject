import { NextResponse, type NextRequest } from "next/server";
import { REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { GEO_COUNTRY_HEADER } from "@/lib/geo";

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
export function proxy(req: NextRequest) {
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

  const res = isGatedAccountPath(req.nextUrl.pathname) && !req.cookies.get(REFRESH_COOKIE)
    ? NextResponse.redirect(loginUrl(req))
    : NextResponse.next({ request: { headers: requestHeaders } });

  // Set on the redirect too: a first-time visitor deep-linking into /account must not come
  // back from login without a market, or they'd be shown the wrong currency.
  if (seed) {
    res.cookies.set(COUNTRY_COOKIE, seed, COUNTRY_COOKIE_OPTIONS);
  }

  return res;
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
