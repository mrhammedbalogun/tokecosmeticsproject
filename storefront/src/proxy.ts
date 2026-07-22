import { NextResponse, type NextRequest } from "next/server";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

// Next.js 16 renamed the `middleware` file convention to `proxy` (Node.js runtime only).
// See node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/proxy.md.
export function proxy(req: NextRequest) {
  const existing = req.cookies.get(COUNTRY_COOKIE)?.value;

  // Forward the geo country to Server Components as a REQUEST header so the (shop)
  // layout can read it via `headers()`. Vercel injects x-vercel-ip-country in prod;
  // it is absent locally, so the banner stays hidden. NEVER redirect — suggestion only.
  const geo = req.headers.get("x-vercel-ip-country") ?? "";
  const requestHeaders = new Headers(req.headers);
  requestHeaders.set("x-geo-country", geo);

  const res = NextResponse.next({ request: { headers: requestHeaders } });

  // Ensure a country cookie exists from the very first request (default NG) so Server
  // Components always have a market. `country` is deliberately NOT httpOnly — client UI
  // reads it. User choice always wins; this only seeds a default when none is set.
  if (!existing) {
    res.cookies.set(COUNTRY_COOKIE, DEFAULT_COUNTRY, {
      httpOnly: false,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 365,
    });
  }

  return res;
}

export const config = {
  // Skip static assets + API routes.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|logos|api).*)"],
};
