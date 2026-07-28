import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { apiFetch, apiFetchRaw, ApiError, type ApiFetchOptions } from "@/lib/api";
import {
  ACCESS_COOKIE, REFRESH_COOKIE, ACCESS_MAX_AGE, REFRESH_MAX_AGE, cookieOptions,
} from "@/lib/auth";
import { decideAuth } from "@/lib/auth-guard";

type Jar = Awaited<ReturnType<typeof cookies>>;

/** Read the current access token (server-only). */
export async function getAccessToken(): Promise<string | undefined> {
  return (await cookies()).get(ACCESS_COOKIE)?.value;
}

/**
 * Its own class so callers can tell the tripwire apart from a failure of the request
 * itself. It is thrown from INSIDE the fetchers (after the probe, before the network),
 * so a caller that wraps a fetcher in try/catch to handle network errors would otherwise
 * swallow the one error that must never be swallowed. Rethrow it on sight.
 */
export class RscCookieWriteError extends Error {
  name = "RscCookieWriteError";
}

/**
 * Dev-time tripwire for the one mistake in this file that costs a real customer their
 * session: calling a refreshing fetcher from a Server Component.
 *
 * WHY IT MATTERS MORE THAN THE CRASH. The refresh endpoint runs SimpleJWT with
 * ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION, so a *successful* refresh blacklists
 * the old refresh token server-side. If we then cannot persist the new pair — and an RSC
 * cannot, see `lib/auth-guard.ts` — the user's 14-day session is irrecoverably dead, and
 * a caller with a `catch` (the product page had one) renders a perfectly normal page over
 * the top of it. Failing before the network call is the whole point.
 *
 * WHY A PROBE RATHER THAN A LINT RULE. The bug arrived *indirectly*, through what is now
 * `lib/orders.ts` (then `lib/checkout.ts`), which Route Handlers may legitimately import
 * — so a no-restricted-imports rule on pages would not have caught it. Cookie MUTATION throws
 * during RSC render (`next/dist/docs/01-app/03-api-reference/04-functions/cookies.md`:
 * ".set, .delete must be performed in a Server Function or Route Handler"), so probing
 * writability detects the real context no matter how many modules deep the call is.
 *
 * Cost: a stray `Set-Cookie: __rsc_write_probe__=; Max-Age=0` on dev Route Handler
 * responses. Deliberate, and cheaper than the bug. Off in production.
 */
function assertCookiesWritable(jar: Jar, fn: string): void {
  if (process.env.NODE_ENV === "production") return;
  try {
    jar.delete(PROBE_COOKIE);
  } catch {
    throw new RscCookieWriteError(
      `${fn}() was called during Server Component render. It cannot persist a rotated ` +
      `token there, and attempting the refresh would blacklist the user's refresh token ` +
      `server-side — silently ending their session. Use requireAuth() or ` +
      `fetchWithAuthOrBounce() from a Server Component, or move this call into a Route ` +
      `Handler.`,
    );
  }
}

const PROBE_COOKIE = "__rsc_write_probe__";

/**
 * Exchange the refresh cookie for a new access token and persist BOTH halves.
 * Route-Handler context only — the caller has already run the probe.
 *
 * SimpleJWT rotates refresh tokens and blacklists the old one on use, so the rotated
 * refresh MUST be stored or the *next* refresh fails and the user is force-logged-out.
 */
async function refreshAndPersist(jar: Jar, refresh: string): Promise<string> {
  const out = await apiFetch<{ access: string; refresh?: string }>("/auth/token/refresh/", {
    method: "POST", body: { refresh },
  });
  jar.set(ACCESS_COOKIE, out.access, cookieOptions({ maxAge: ACCESS_MAX_AGE }));
  if (out.refresh) {
    jar.set(REFRESH_COOKIE, out.refresh, cookieOptions({ maxAge: REFRESH_MAX_AGE }));
  }
  return out.access;
}

/**
 * Authenticated server-side fetch with a single silent refresh: if the access token
 * is rejected (401), swap the refresh token for a fresh access token, persist it, and
 * retry once.
 *
 * ROUTE HANDLERS AND SERVER FUNCTIONS ONLY — it writes cookies. Server Components must
 * use `fetchWithAuthOrBounce`, which redirects through the renewal Route Handler instead.
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
 * Like `fetchWithAuth`, but hands back the raw `Response` — for proxying a binary body
 * (the invoice PDF) through a BFF route without buffering or parsing it. The caller owns
 * the status mapping; nothing here throws on a non-ok status.
 *
 * ROUTE HANDLERS AND SERVER FUNCTIONS ONLY — it writes cookies on renewal.
 *
 * On a 401 there is nothing to "retry" about the first Response: we issue a whole new
 * request, which yields a new Response, so the consumed-body problem never arises. The
 * rejected body IS explicitly released — an unread body pins the underlying connection.
 *
 * Request-body replay is safe only because `apiFetchRaw` re-serialises `opts.body` to
 * JSON on each attempt. If streaming request bodies are ever added, the retry must be
 * disabled for them — a stream cannot be sent twice.
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

  await res.body?.cancel();
  const access = await refreshAndPersist(jar, refresh);
  return apiFetchRaw(path, { ...opts, token: access });
}

/**
 * The Server-Component gate. Returns the access token, or redirects — through the
 * renewal Route Handler if the session is merely stale, to login if it is gone.
 *
 * `currentPath` is an explicit required parameter because Next 16 gives a Server
 * Component no way to read its own pathname (`headers()` exposes only incoming request
 * headers). A proxy-injected header was the alternative and was rejected: it fails
 * SILENTLY when the matcher misses a route or the header name drifts, quietly sending
 * users to DEFAULT_NEXT instead. A wrong literal is caught in one walkthrough; a silent
 * infrastructure fallback is not. Dynamic routes build it from their own awaited params.
 */
export async function requireAuth(currentPath: string): Promise<string> {
  const jar = await cookies();
  const decision = decideAuth(
    jar.get(ACCESS_COOKIE)?.value,
    jar.get(REFRESH_COOKIE)?.value,
    currentPath,
  );
  if (decision.kind === "authenticated") return decision.token;
  redirect(decision.to);
}

/**
 * Authenticated fetch for SERVER COMPONENTS. Reads cookies, never writes them: on a 401
 * it hands the renewal off to `/api/auth/refresh-redirect`, which is allowed to persist
 * the rotated pair, and which sends the user back here afterwards.
 *
 * It must never call the refresh endpoint itself — see `assertCookiesWritable` for why a
 * successful-but-unpersisted rotation is worse than an error.
 *
 * Callers that wrap this in try/catch MUST `unstable_rethrow` (or rethrow non-ApiError
 * errors, as `loadOrder` in the confirmation page does): `redirect()` works by throwing
 * NEXT_REDIRECT, and a catch-all would swallow the bounce.
 */
export async function fetchWithAuthOrBounce<T = unknown>(
  path: string,
  currentPath: string,
  opts: ApiFetchOptions = {},
): Promise<T> {
  const jar = await cookies();
  const token = jar.get(ACCESS_COOKIE)?.value;

  let bounceTo: string;
  try {
    return await apiFetch<T>(path, { ...opts, token });
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 401) throw e;
    // "the backend rejected this access token" is semantically the same state as "there
    // is no access token", so the same pure decision function answers both.
    const decision = decideAuth(undefined, jar.get(REFRESH_COOKIE)?.value, currentPath);
    if (decision.kind === "authenticated") throw e; // unreachable: access is undefined
    bounceTo = decision.to;
  }
  // Outside the catch on purpose — redirect() throws, and Next's docs are explicit that
  // it belongs outside try/catch (`.../04-functions/redirect.md`: "redirect throws an
  // error so it should be called outside the try block").
  redirect(bounceTo);
}
