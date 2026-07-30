/**
 * Renew the admin token pair, then send the staff member back where they were going.
 *
 * WHY THIS EXISTS. Server Components may read cookies but never write them (Next 16 —
 * `01-app/03-api-reference/04-functions/cookies.md`). The backend rotates refresh tokens
 * and blacklists the old one on every use, so a renewal produces a NEW pair that MUST be
 * persisted, and persisting is only legal in a Route Handler or Server Function. An admin
 * page that finds an expired access token therefore cannot fix it in place: it redirects
 * here, this handler renews and stores, and the browser is returned to its destination.
 *
 * IT IS LOAD-BEARING HERE IN A WAY IT IS NOT ON THE STOREFRONT. The admin access cookie
 * lives ten minutes, so this runs several times in any real working session rather than
 * twice an hour.
 *
 * A GET (not POST) precisely because it is reached by redirecting a navigating browser.
 * It is safe to expose: without a valid refresh cookie it does nothing at all, and it
 * performs no action a visitor could not already trigger by loading an admin page.
 */
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { ApiError } from "@/lib/api";
import { ACCESS_COOKIE, PREAUTH_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { LOGIN_PATH } from "@/lib/auth-guard";
import { refreshAndPersist } from "@/lib/session";
import { safeNext } from "@/lib/next-param";

export async function GET(req: Request) {
  const url = new URL(req.url);
  // Validate BEFORE use. This value decides where an authenticated browser lands, which is
  // exactly the shape of a login open-redirect.
  const next = safeNext(url.searchParams.get("next"));
  const toLogin = new URL(`${LOGIN_PATH}?next=${encodeURIComponent(next)}`, url.origin);

  const jar = await cookies();
  const refresh = jar.get(REFRESH_COOKIE)?.value;

  // The anomaly row of the gate matrix, handled here too because this route is reached by
  // redirect and must not become the one door that tolerates the impossible state.
  if (jar.get(PREAUTH_COOKIE)) {
    jar.delete(ACCESS_COOKIE);
    jar.delete(REFRESH_COOKIE);
    jar.delete(PREAUTH_COOKIE);
    return NextResponse.redirect(new URL(LOGIN_PATH, url.origin), 303);
  }

  // No session at all: don't call the API just to be told so.
  if (!refresh) return NextResponse.redirect(toLogin, 303);

  try {
    await refreshAndPersist(jar, refresh);
    return NextResponse.redirect(new URL(next, url.origin), 303);
  } catch (e) {
    // Distinguish "the token is dead" from "the API did not answer". A bare catch here
    // would treat a 502, a timeout or a deploy blip as a dead token and throw away a valid
    // session for everyone whose access token happened to be stale during the outage — a
    // self-inflicted mass logout from a transient error. (Learned on the storefront; the
    // same code, the same lesson.)
    //
    // Only SimpleJWT's own verdicts destroy cookies: 401 for a rejected token, 400 for one
    // that is invalid or already spent (the rotation-race loser). Clearing on those is
    // what makes the gate TERMINATE — with both cookies gone the login page falls through
    // to the form instead of bouncing back here.
    if (e instanceof ApiError && (e.status === 401 || e.status === 400)) {
      jar.delete(ACCESS_COOKIE);
      jar.delete(REFRESH_COOKIE);
    }
    return NextResponse.redirect(toLogin, 303);
  }
}
