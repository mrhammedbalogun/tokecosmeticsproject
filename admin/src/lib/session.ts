/**
 * Server-side session mechanics: read the cookies, ask `lib/auth-guard.ts` what to do,
 * do it. This module is where the gate matrix becomes behaviour.
 *
 * The renewal design is inherited wholesale from the storefront because the constraint
 * is identical: Server Components may READ cookies but never WRITE them (Next 16,
 * `01-app/03-api-reference/04-functions/cookies.md`), and the backend runs SimpleJWT with
 * ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION, so a *successful* refresh whose new
 * pair cannot be persisted has destroyed the session. An expired access token therefore
 * cannot be renewed where it is noticed; the request is bounced through a Route Handler
 * that renews and returns.
 *
 * That matters more here than on the storefront, not less: the admin access cookie lives
 * ten minutes, so this path runs several times in any real working session.
 */
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { ApiError, apiFetch, apiFetchRaw, drainBody, type ApiFetchOptions } from "@/lib/api";
import { ACCESS_COOKIE, ACCESS_MAX_AGE, PREAUTH_COOKIE, REFRESH_COOKIE, REFRESH_MAX_AGE, cookieOptions } from "@/lib/auth";
import {
  LOGIN_PATH,
  type AdminCookies,
  type RouteClass,
  decideAuth,
} from "@/lib/auth-guard";

type Jar = Awaited<ReturnType<typeof cookies>>;

const PROBE_COOKIE = "__rsc_write_probe__";

export async function readAdminCookies(): Promise<AdminCookies> {
  const jar = await cookies();
  return {
    access: jar.get(ACCESS_COOKIE)?.value,
    refresh: jar.get(REFRESH_COOKIE)?.value,
    preauth: jar.get(PREAUTH_COOKIE)?.value,
  };
}

/**
 * Its own class so callers can tell the tripwire apart from a failure of the request
 * itself. Thrown from INSIDE the fetchers, before the network, so a caller that wraps a
 * fetcher in try/catch to handle network errors cannot swallow the one error that must
 * never be swallowed. Rethrow it on sight.
 */
export class RscCookieWriteError extends Error {
  name = "RscCookieWriteError";
}

/**
 * Dev-time tripwire for the one mistake in this file that costs an administrator their
 * session: calling a refreshing fetcher from a Server Component. Cookie MUTATION throws
 * during RSC render, so probing writability detects the real context no matter how many
 * modules deep the call is — which a lint rule on page files cannot do.
 */
function assertCookiesWritable(jar: Jar, fn: string): void {
  if (process.env.NODE_ENV === "production") return;
  try {
    jar.delete(PROBE_COOKIE);
  } catch {
    throw new RscCookieWriteError(
      `${fn}() was called during Server Component render. It cannot persist a rotated ` +
        `token there, and attempting the refresh would blacklist the refresh token ` +
        `server-side — silently ending the session. Use requireAdmin() or ` +
        `fetchWithAuthOrBounce() from a Server Component, or move this call into a ` +
        `Route Handler.`,
    );
  }
}

/**
 * Exchange the refresh cookie for a new access token and persist BOTH halves.
 * Route-Handler / Server-Function context only.
 *
 * `storeSession` is not used here on purpose: this path must not touch the preauth
 * cookie. Reaching it means a session already exists, so there is nothing to clear, and
 * an unconditional delete would be a write nobody asked for on the hot path.
 */
export async function refreshAndPersist(jar: Jar, refresh: string): Promise<string> {
  const out = await apiFetch<{ access: string; refresh?: string }>("/auth/token/refresh/", {
    method: "POST",
    body: { refresh },
  });
  jar.set(ACCESS_COOKIE, out.access, cookieOptions({ maxAge: ACCESS_MAX_AGE }));
  if (out.refresh) {
    jar.set(REFRESH_COOKIE, out.refresh, cookieOptions({ maxAge: REFRESH_MAX_AGE }));
  }
  return out.access;
}

/**
 * The gate for pages that are not app pages: `/login`, `/accept-invite`, `/totp`.
 * Redirects or purges per the matrix; returns nothing when the page may render.
 */
export async function gatePage(routeClass: RouteClass, currentPath: string): Promise<void> {
  const jar = await cookies();
  const decision = decideAuth(cookiesFromJar(jar), routeClass, currentPath);
  // A `purge` decision redirects to the purge Route Handler rather than clearing here:
  // this runs during Server Component render, where a cookie WRITE throws. See PURGE_PATH.
  if (decision.kind === "purge" || decision.kind === "redirect") redirect(decision.to);
}

/**
 * The gate for every real admin page. Returns the access token, or redirects — to the
 * TOTP step if the ceremony is half-done, through the renewal handler if the session is
 * merely stale, to login if it is gone.
 *
 * `currentPath` is an explicit required parameter because Next 16 gives a Server
 * Component no way to read its own pathname. A proxy-injected header was the alternative
 * and is rejected for the same reason the storefront rejects it: it fails SILENTLY when
 * the matcher misses a route or the header name drifts.
 */
export async function requireAdmin(currentPath: string): Promise<string> {
  const jar = await cookies();
  const decision = decideAuth(cookiesFromJar(jar), "app", currentPath);
  if (decision.kind === "authenticated") return decision.token;
  // Every remaining branch of the "app" matrix carries a destination — including `purge`,
  // whose destination is the Route Handler that is ALLOWED to delete cookies.
  redirect("to" in decision ? decision.to : LOGIN_PATH);
}

/**
 * The gate for the TOTP step. Returns the preauth token itself, because the three
 * ceremony Server Functions need it as a bearer credential.
 */
export async function requirePreauth(): Promise<string> {
  const jar = await cookies();
  const decision = decideAuth(cookiesFromJar(jar), "totp", "/totp");
  if (decision.kind !== "allow") redirect("to" in decision ? decision.to : LOGIN_PATH);
  return jar.get(PREAUTH_COOKIE)!.value;
}

/**
 * The preauth token, or undefined — for the ceremony's Server Functions, which must
 * handle its absence by clearing and bouncing rather than by redirecting mid-action.
 */
export async function getPreauthToken(): Promise<string | undefined> {
  return (await cookies()).get(PREAUTH_COOKIE)?.value;
}

function cookiesFromJar(jar: Jar): AdminCookies {
  return {
    access: jar.get(ACCESS_COOKIE)?.value,
    refresh: jar.get(REFRESH_COOKIE)?.value,
    preauth: jar.get(PREAUTH_COOKIE)?.value,
  };
}

/**
 * Authenticated fetch with a single silent refresh. ROUTE HANDLERS AND SERVER FUNCTIONS
 * ONLY — it writes cookies. Server Components must use `fetchWithAuthOrBounce`.
 *
 * It reads `admin_access` and ONLY `admin_access`. It does not fall back to the preauth
 * cookie, and it must never grow such a fallback: a preauth token is defined to open
 * three endpoints, and a helper that reaches for "whichever token cookie exists" is how
 * a credential quietly starts doing something its own definition forbids.
 */
export async function fetchWithAuth<T = unknown>(
  path: string,
  opts: ApiFetchOptions = {},
): Promise<T> {
  const jar = await cookies();
  assertCookiesWritable(jar, "fetchWithAuth");
  const token = jar.get(ACCESS_COOKIE)?.value;
  try {
    return await apiFetch<T>(path, { ...opts, token });
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 401) throw e;
    const refresh = jar.get(REFRESH_COOKIE)?.value;
    if (!refresh) throw e;
    const access = await refreshAndPersist(jar, refresh);
    return apiFetch<T>(path, { ...opts, token: access });
  }
}

/**
 * Like `fetchWithAuth` but hands back the raw `Response`, for the generic BFF proxy which
 * owns its own status mapping. The rejected body is explicitly DRAINED, never cancelled —
 * see `drainBody`.
 */
export async function fetchWithAuthRaw(
  path: string,
  opts: ApiFetchOptions = {},
): Promise<Response> {
  const jar = await cookies();
  assertCookiesWritable(jar, "fetchWithAuthRaw");
  const token = jar.get(ACCESS_COOKIE)?.value;

  const res = await apiFetchRaw(path, { ...opts, token });
  if (res.status !== 401) return res;

  const refresh = jar.get(REFRESH_COOKIE)?.value;
  if (!refresh) return res;

  await drainBody(res);
  const access = await refreshAndPersist(jar, refresh);
  return apiFetchRaw(path, { ...opts, token: access });
}

/**
 * Authenticated fetch for SERVER COMPONENTS. Reads cookies, never writes them: on a 401
 * it hands renewal off to `/api/auth/refresh-redirect`, which may persist the rotated
 * pair and which sends the user back here afterwards.
 *
 * Callers that wrap this in try/catch MUST rethrow non-ApiError errors: `redirect()`
 * works by throwing NEXT_REDIRECT, and a catch-all would swallow the bounce.
 */
export async function fetchWithAuthOrBounce<T = unknown>(
  path: string,
  currentPath: string,
  opts: ApiFetchOptions = {},
): Promise<T> {
  const jar = await cookies();
  const token = jar.get(ACCESS_COOKIE)?.value;

  // No token → decide the bounce BEFORE touching the API. There is nothing to be
  // optimistic about without one, and it spares the API a guaranteed-useless request.
  if (!token) {
    const decision = decideAuth(cookiesFromJar(jar), "app", currentPath);
    if (decision.kind !== "authenticated") {
      redirect("to" in decision ? decision.to : LOGIN_PATH);
    }
  }

  let bounceTo: string;
  try {
    return await apiFetch<T>(path, { ...opts, token });
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 401) throw e;
    // "the backend rejected this access token" is the same state as "there is no access
    // token", so the same pure decision function answers both.
    const decision = decideAuth(
      { ...cookiesFromJar(jar), access: undefined },
      "app",
      currentPath,
    );
    if (decision.kind === "authenticated") throw e; // unreachable: access is undefined
    bounceTo = "to" in decision ? decision.to : LOGIN_PATH;
  }
  // Outside the catch on purpose — `redirect()` throws, and Next's docs are explicit that
  // it belongs outside the try block.
  redirect(bounceTo);
}
