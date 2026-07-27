/**
 * Renew the token pair, then send the user back where they were going.
 *
 * WHY THIS EXISTS. Server Components may read cookies but never write them (Next 16 —
 * `01-app/03-api-reference/04-functions/cookies.md`). The backend rotates refresh tokens
 * and blacklists the old one on every use, so a renewal produces a NEW pair that MUST be
 * persisted. Persisting is only legal in a Route Handler or Server Function — so an
 * account page that finds an expired access token cannot fix it in place. It redirects
 * here, this handler renews and stores, and the user is returned to their destination.
 *
 * A GET (not POST) precisely because it is reached by redirecting a navigating browser.
 * It is safe to expose: it performs no action a visitor could not already trigger by
 * loading an account page, and without a valid refresh cookie it does nothing at all.
 *
 * Deliberately a separate file rather than another case in `api/auth/[action]`: that
 * handler is POST-only and answers in JSON, and mixing a redirect response into it would
 * blur both contracts.
 */
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { apiFetch } from "@/lib/api";
import {
  ACCESS_COOKIE, ACCESS_MAX_AGE, REFRESH_COOKIE, REFRESH_MAX_AGE, cookieOptions,
} from "@/lib/auth";
import { LOGIN_PATH } from "@/lib/auth-guard";
import { safeNext } from "@/lib/next-param";

export async function GET(req: Request) {
  const url = new URL(req.url);
  // Validate BEFORE use. This value decides where an authenticated browser lands, which
  // is exactly the shape of a login open-redirect.
  const next = safeNext(url.searchParams.get("next"));
  const toLogin = new URL(`${LOGIN_PATH}?next=${encodeURIComponent(next)}`, url.origin);

  const jar = await cookies();
  const refresh = jar.get(REFRESH_COOKIE)?.value;
  // No session at all: don't call the API just to be told so.
  if (!refresh) return NextResponse.redirect(toLogin, 303);

  try {
    const out = await apiFetch<{ access: string; refresh?: string }>("/auth/token/refresh/", {
      method: "POST", body: { refresh },
    });
    jar.set(ACCESS_COOKIE, out.access, cookieOptions({ maxAge: ACCESS_MAX_AGE }));
    // The rotated refresh MUST be stored: the one we just spent is blacklisted, so
    // dropping the replacement kills the session on the very next renewal.
    if (out.refresh) {
      jar.set(REFRESH_COOKIE, out.refresh, cookieOptions({ maxAge: REFRESH_MAX_AGE }));
    }
    return NextResponse.redirect(new URL(next, url.origin), 303);
  } catch {
    // The refresh token is dead — expired, or blacklisted because a concurrent request
    // rotated it first. Clear BOTH cookies: leaving the dead one in place would send the
    // account gate straight back here, looping the user indefinitely.
    jar.delete(ACCESS_COOKIE);
    jar.delete(REFRESH_COOKIE);
    return NextResponse.redirect(toLogin, 303);
  }
}
