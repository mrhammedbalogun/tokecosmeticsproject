/**
 * Session mechanics for the delivery-partner portal (Plan-39) — the partner twin of
 * `lib/session.ts`, kept separate so neither credential pair can leak into the
 * other's helpers.
 *
 * DELIBERATELY SMALLER than the admin machinery: the portal has no Server-Component
 * data fetching (the rates page is a client component talking to the partner BFF
 * proxy), so there is no refresh-redirect bounce to build — every fetch here runs in
 * a Route Handler or Server Function, where cookies may be written and a rotated
 * refresh pair can always be persisted.
 */
import { cookies } from "next/headers";
import { ApiError, apiFetch, apiFetchRaw, drainBody, type ApiFetchOptions } from "@/lib/api";
import { cookieOptions } from "@/lib/auth";
import {
  PARTNER_ACCESS_COOKIE,
  PARTNER_ACCESS_MAX_AGE,
  PARTNER_REFRESH_COOKIE,
  PARTNER_REFRESH_MAX_AGE,
} from "@/lib/partner-auth";

type Jar = Awaited<ReturnType<typeof cookies>>;

export function storePartnerSession(jar: Jar, pair: { access: string; refresh: string }): void {
  jar.set(PARTNER_ACCESS_COOKIE, pair.access, cookieOptions({ maxAge: PARTNER_ACCESS_MAX_AGE }));
  jar.set(PARTNER_REFRESH_COOKIE, pair.refresh, cookieOptions({ maxAge: PARTNER_REFRESH_MAX_AGE }));
}

export function clearPartnerSession(jar: Jar): void {
  jar.delete(PARTNER_ACCESS_COOKIE);
  jar.delete(PARTNER_REFRESH_COOKIE);
}

/**
 * Exchange the partner refresh cookie for a new access token and persist both halves.
 * The shared `/auth/token/refresh/` endpoint serves partner tokens too — the audience
 * claim rides the refresh token and SimpleJWT copies it onto every renewed access
 * token (see backend `mint_partner_token_pair`).
 */
export async function partnerRefreshAndPersist(jar: Jar, refresh: string): Promise<string> {
  const out = await apiFetch<{ access: string; refresh?: string }>("/auth/token/refresh/", {
    method: "POST",
    body: { refresh },
  });
  jar.set(PARTNER_ACCESS_COOKIE, out.access, cookieOptions({ maxAge: PARTNER_ACCESS_MAX_AGE }));
  if (out.refresh) {
    jar.set(PARTNER_REFRESH_COOKIE, out.refresh, cookieOptions({ maxAge: PARTNER_REFRESH_MAX_AGE }));
  }
  return out.access;
}

/**
 * Authenticated raw fetch with a single silent refresh — the partner proxy's engine.
 * Route Handlers and Server Functions only (it writes cookies on the refresh path).
 * Reads `partner_access` and ONLY `partner_access`, for the same credential-definition
 * reason `fetchWithAuth` reads only `admin_access`.
 */
export async function partnerFetchRaw(path: string, opts: ApiFetchOptions = {}): Promise<Response> {
  const jar = await cookies();
  const token = jar.get(PARTNER_ACCESS_COOKIE)?.value;

  const res = await apiFetchRaw(path, { ...opts, token });
  if (res.status !== 401) return res;

  const refresh = jar.get(PARTNER_REFRESH_COOKIE)?.value;
  if (!refresh) return res;

  await drainBody(res);
  let access: string;
  try {
    access = await partnerRefreshAndPersist(jar, refresh);
  } catch (e) {
    // A dead refresh token is a signed-out portal, not an error page: clear the pair
    // so the proxy's presence check sends the next navigation to the login.
    if (e instanceof ApiError && (e.status === 401 || e.status === 400)) {
      clearPartnerSession(jar);
      return new Response(JSON.stringify({ detail: "Session expired." }), {
        status: 401,
        headers: { "content-type": "application/json" },
      });
    }
    throw e;
  }
  return apiFetchRaw(path, { ...opts, token: access });
}
