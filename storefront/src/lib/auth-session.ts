/**
 * Establishing and tearing down a browser session — the ONE implementation.
 *
 * Extracted from `app/api/auth/[action]/route.ts` when the Plan-15 `/login` page arrived
 * as a Server Function. Both surfaces may legally write cookies, but a Server Action
 * cannot reuse a Route Handler by fetching it: `Set-Cookie` on a fetch response does not
 * propagate to the outer response, so the user would authenticate and still be logged out.
 * Sharing this module rather than the route is what keeps one code path.
 *
 * That matters most for the guest-cart merge. It belongs to *authenticating*, not to
 * whichever page remembered to call it — it used to live in checkout's `SignInStep`, so a
 * shopper who signed in from the header silently lost their bag. A lib module enforces
 * "no future sign-in surface can omit it" better than a route file does.
 *
 * Every function takes the cookie jar explicitly instead of calling `cookies()` itself.
 * That keeps them testable without mocking `next/headers`, and it puts the "must run
 * somewhere cookie writes are legal" requirement in plain sight at every call site.
 */
import type { cookies } from "next/headers";
import { apiFetch } from "@/lib/api";
import {
  ACCESS_COOKIE, CART_COOKIE, REFRESH_COOKIE, ACCESS_MAX_AGE, REFRESH_MAX_AGE, cookieOptions,
} from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

export type Jar = Awaited<ReturnType<typeof cookies>>;

export interface TokenPair {
  access: string;
  refresh: string;
}

export function setTokens(jar: Jar, access?: string, refresh?: string): void {
  if (access) jar.set(ACCESS_COOKIE, access, cookieOptions({ maxAge: ACCESS_MAX_AGE }));
  if (refresh) jar.set(REFRESH_COOKIE, refresh, cookieOptions({ maxAge: REFRESH_MAX_AGE }));
}

export function clearTokens(jar: Jar): void {
  jar.delete(ACCESS_COOKIE);
  jar.delete(REFRESH_COOKIE);
  // Drop the cart pointer too, so a signed-out browser never carries a user-cart id.
  // Not a leak if it lingered (the backend ignores a cart that belongs to a user), but it
  // keeps the cookie's meaning strictly "the guest cart in this browser".
  jar.delete(CART_COOKIE);
}

/**
 * Fold the guest cart into the account that just authenticated.
 *
 * Best-effort by design — see the swallowed catch below for why a failure must not surface.
 *
 * Four details here are load-bearing; do not "simplify" any of them away:
 *  - the token comes from the login RESPONSE, never `jar.get(ACCESS_COOKIE)`: mid-handler
 *    the jar still reflects the INCOMING request, because `jar.set` only stages a cookie
 *    on the outgoing response;
 *  - the country cookie is forwarded, or `get_or_create` mints an NG cart for a UK shopper
 *    who has no user cart yet;
 *  - errors are swallowed HERE, locally, so a caller's catch-all cannot report a failed
 *    login to a user who is in fact logged in, cookies and all;
 *  - it is NOT wired into refresh or me — no identity transition, and refresh runs
 *    constantly.
 */
export async function mergeGuestCart(jar: Jar, accessToken: string): Promise<void> {
  const guestCartId = jar.get(CART_COOKIE)?.value;
  if (!guestCartId) return;
  // The backend ignores foreign, claimed, converted and malformed ids (it filters on
  // `user__isnull=True`), and merging twice is a no-op — so a stale or hostile cookie
  // value cannot move someone else's cart into this account.
  try {
    const merged = await apiFetch<{ id?: string }>("/cart/merge/", {
      method: "POST",
      body: { cart_id: guestCartId },
      token: accessToken,
      country: jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY,
    });
    // Point the browser at the surviving cart; the guest one is now converted.
    if (merged?.id) jar.set(CART_COOKIE, merged.id, cookieOptions());
  } catch {
    // Swallowed deliberately — see the doc comment above.
  }
}

/**
 * Exchange credentials for a token pair, persist both cookies, and fold in the guest cart.
 * Throws `ApiError` if the credentials are rejected, so the caller owns the error copy.
 *
 * Cookie-writing context only (Route Handler or Server Function).
 */
export async function establishSession(
  jar: Jar,
  credentials: { email: string; password: string },
): Promise<TokenPair> {
  const tokens = await apiFetch<TokenPair>("/auth/token/", {
    method: "POST", body: credentials,
  });
  setTokens(jar, tokens.access, tokens.refresh);
  await mergeGuestCart(jar, tokens.access);
  return tokens;
}

export interface RegisterPayload {
  email: string;
  password: string;
  first_name: string;
  last_name?: string;
  phone?: string;
  marketing_consent?: boolean;
}

/**
 * Create an account and sign the new user straight in.
 *
 * Two calls, because Django's register endpoint does not return tokens. Shared so the
 * `/register` Server Action and the JSON BFF cannot drift apart on the order of
 * operations or on the guest-cart merge.
 *
 * A rejected registration throws before any login is attempted — following a 400 with a
 * token request would mean submitting the supplied password against an account that may
 * belong to somebody else (the usual 400 here is "Account already exists").
 */
export async function registerSession(
  jar: Jar,
  payload: RegisterPayload,
): Promise<TokenPair> {
  await apiFetch("/auth/register/", { method: "POST", body: payload });
  return establishSession(jar, { email: payload.email, password: payload.password });
}
