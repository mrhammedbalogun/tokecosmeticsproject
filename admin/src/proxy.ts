import { NextResponse, type NextRequest } from "next/server";
import { ACCESS_COOKIE, PREAUTH_COOKIE, REFRESH_COOKIE } from "@/lib/auth";

// Next.js 16 renamed the `middleware` file convention to `proxy` (Node.js runtime only).
// See node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/proxy.md.
//
// Only ONE proxy file may exist, so everything that must run before a route renders lives
// here. Keep it dependency-free: the docs warn it may be deployed to the CDN edge,
// separate from render code, so it must not import shared modules with real behaviour —
// cookie-name constants only, never lib/session.ts.
//
// ── THIS IS A ROUTER, NOT THE GATE ───────────────────────────────────────────────────
//
// It cannot verify a token, so nothing it does is authorization; the storefront says the
// same thing about its own `/account` check ("presence theatre, deliberately") and the
// lesson transfers exactly. Its jobs are to avoid rendering an admin page for an
// obviously-signed-out visitor, to attach a correct `?next=`, and to send a half-way
// visitor to the step they actually owe. The real per-request boundary is
// `lib/auth-guard.decideAuth`, consulted by every page and every BFF route — and the
// load-bearing fence is the backend, which refuses a preauth token everywhere but the
// three TOTP endpoints regardless of anything decided here.
//
// The duplication with `decideAuth` is accepted rather than factored out: importing the
// guard would break the dependency-free rule above, and a router that disagrees with the
// gate produces a redirect loop at worst, never an unauthorized render.
export function proxy(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const preauth = Boolean(req.cookies.get(PREAUTH_COOKIE));
  const session = Boolean(req.cookies.get(ACCESS_COOKIE) || req.cookies.get(REFRESH_COOKIE));

  const res = redirectFor(req, pathname, preauth, session) ?? NextResponse.next();

  // NO-STORE ON EVERYTHING THIS MATCHES. Admin responses carry order data, customer
  // addresses and staff identities; a copy of any of them in a shared cache, a corporate
  // proxy or a browser's back-forward cache is a PII finding waiting to happen. Set here
  // rather than in `next.config.ts` because this file's matcher already excludes the
  // immutable static chunks, which SHOULD stay cacheable.
  //
  // There is also deliberately NO service worker in this app, for the same reason.
  res.headers.set("Cache-Control", "no-store, no-cache, must-revalidate, private");
  res.headers.set("Pragma", "no-cache");
  return res;
}

function redirectFor(
  req: NextRequest,
  pathname: string,
  preauth: boolean,
  session: boolean,
): NextResponse | null {
  // BFF routes are never redirected: they answer with status codes, and a fetch() that
  // silently followed a redirect to `/login` would get an HTML page where it expected
  // JSON. Checked FIRST, ahead of the anomaly, so the Route Handler is the thing that
  // clears the cookies and answers 401 — it can do both; this file can only redirect.
  if (isSegment(pathname, "/api")) return null;

  // Anomaly: the two credential sets are written mutually exclusively, so holding both is
  // a state nothing legitimate produces. Fail closed.
  //
  // IT REDIRECTS TO THE PURGE HANDLER, NOT TO `/login`. Redirecting to `/login` while the
  // cookies stayed put was an infinite redirect — `/login` is itself gated, saw the same
  // anomaly, and bounced again with nothing in the cycle able to remove the cookies
  // (a Server Component cannot delete one). `/api/auth/purge` is ungated, clears all
  // three, and sends the browser on. Found by walking this matrix over real HTTP against
  // a production build; the unit tests could not show it, because each layer's answer was
  // individually correct.
  if (preauth && session) {
    // Literal, like every other path in this file: importing `auth-guard.PURGE_PATH`
    // would drag `next-param` in with it and break the dependency-free rule above.
    const res = NextResponse.redirect(new URL("/api/auth/purge", req.nextUrl));
    // Belt and braces: the handler is what actually guarantees the clear, but deleting
    // here too means the bad state is gone even if that redirect is never followed.
    for (const name of [ACCESS_COOKIE, REFRESH_COOKIE, PREAUTH_COOKIE]) res.cookies.delete(name);
    return res;
  }

  if (isSegment(pathname, "/accept-invite")) return null; // public by design

  if (isSegment(pathname, "/login")) {
    if (preauth) return NextResponse.redirect(new URL("/totp", req.nextUrl));
    if (session) return NextResponse.redirect(new URL("/", req.nextUrl));
    return null;
  }

  if (isSegment(pathname, "/totp")) {
    if (preauth) return null;
    if (session) return NextResponse.redirect(new URL("/", req.nextUrl));
    return NextResponse.redirect(new URL("/login", req.nextUrl));
  }

  // Every real admin page.
  if (session) return null;
  // Preauth only -> the step they owe, NOT /login. Step one is already done, and sending
  // them back to a password form would burn a Turnstile token and a throttle slot to
  // re-prove something they proved a minute ago.
  if (preauth) return NextResponse.redirect(new URL("/totp", req.nextUrl));
  return NextResponse.redirect(loginUrl(req));
}

/** Exact segment match — `/login-help` is not the login page. */
function isSegment(pathname: string, base: string): boolean {
  return pathname === base || pathname.startsWith(`${base}/`);
}

function loginUrl(req: NextRequest): URL {
  const url = new URL("/login", req.nextUrl);
  // Only the path — never the full URL. Round-tripping an absolute URL through `next` is
  // how open redirects start; `safeNext` on the reading side rejects those anyway.
  url.searchParams.set("next", req.nextUrl.pathname + req.nextUrl.search);
  return url;
}

export const config = {
  // Every route except the immutable static chunks, the image optimizer and the favicon.
  // Exclusions are anchored so a future `/_next/staticky` cannot slip through.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
