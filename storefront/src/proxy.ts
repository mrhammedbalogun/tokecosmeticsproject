import { NextResponse, type NextRequest } from "next/server";
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

// Next.js 16 renamed the `middleware` file convention to `proxy` (Node.js runtime only).
// See node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/proxy.md.
export function proxy(req: NextRequest) {
  const existing = req.cookies.get(COUNTRY_COOKIE)?.value;

  // Trust ONLY the platform-injected geo header (Vercel sets x-vercel-ip-country in prod).
  // We overwrite the forwarded x-geo-country with it, so a client-spoofed x-geo-country on
  // the incoming request can never reach Server Components. Absent locally -> "" -> the
  // banner stays hidden. NEVER redirect — this is a suggestion only.
  const geo = req.headers.get("x-vercel-ip-country") ?? "";
  const requestHeaders = new Headers(req.headers);
  requestHeaders.set(GEO_COUNTRY_HEADER, geo);

  const res = NextResponse.next({ request: { headers: requestHeaders } });

  // Seed a country cookie on the very first request (default NG) so Server Components always
  // have a market. Only when absent — an existing choice is never overwritten.
  if (!existing) {
    res.cookies.set(COUNTRY_COOKIE, DEFAULT_COUNTRY, COUNTRY_COOKIE_OPTIONS);
  }

  return res;
}

export const config = {
  // Run on every route except static assets, the image optimizer, favicon, /logos, and /api.
  // Exclusions are anchored (trailing slash / exact filename) so prefix collisions such as a
  // future /api-docs or /logos-landing still get the proxy.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|logos/|api/).*)"],
};
