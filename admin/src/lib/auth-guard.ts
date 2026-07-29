/**
 * THE ADMIN GATE. Given the three session cookies and which family of route is being
 * asked for, decide what happens next. Pure — no `cookies()`, no `redirect()`, no fetch —
 * so that every row of the matrix below is asserted by a test that observes a RETURN
 * VALUE rather than thrown control flow. `redirect()` works by throwing NEXT_REDIRECT;
 * folding the decision into it would mean the interesting logic could only be observed
 * through an exception.
 *
 * ── WHERE THE BOUNDARY ACTUALLY IS ────────────────────────────────────────────────
 *
 * Here, and in `lib/session.ts` which acts on it — NOT in `proxy.ts`. The storefront says
 * this about its own proxy and it is worth repeating rather than rediscovering: the
 * proxy's cookie check is "presence theatre, deliberately… not authorization". It cannot
 * verify a token, it may be deployed to a CDN edge separate from the render code, and it
 * has no way to fail closed if its matcher drifts. It exists to avoid rendering pages for
 * an obviously-logged-out visitor and to attach a correct `?next=`. This module is what
 * every page and every BFF route actually consults.
 *
 * ── AND WHICH LAYER IS LOAD-BEARING ───────────────────────────────────────────────
 *
 * Neither. The real fence is the BACKEND, behaviourally: `CustomerJWTAuthentication` is
 * the project default and refuses preauth tokens outright, the three preauth-accepting
 * views are enumerated and guard-tested, and `AdminJWTAuthentication` accepts only tokens
 * carrying the `toke-admin` audience — which is minted in exactly one function, called
 * from exactly one view, after TOTP verifies. A preauth token therefore gets a 401 from
 * every endpoint outside those three no matter what this file does.
 *
 * That is not a reason to build this loosely. It is the reason a bug here is a UX
 * incident rather than a security one, and knowing which is which is what stops a gate
 * from being mistaken for the fence. Built fail-closed anyway: every state not enumerated
 * below purges the cookies and returns to `/login`.
 *
 * ── THE MATRIX ────────────────────────────────────────────────────────────────────
 *
 * | state          | /login          | /totp           | app route            | BFF        |
 * |----------------|-----------------|-----------------|----------------------|------------|
 * | none           | allow           | -> /login       | -> /login?next=      | 401        |
 * | preauth only   | -> /totp        | allow           | -> /totp (NOT login) | 401        |
 * | session pair   | -> dashboard    | -> dashboard    | authenticated        | authed     |
 * | refresh only   | -> dashboard    | -> dashboard    | renewal bounce       | renew      |
 * | preauth + pair | purge -> /login | purge -> /login | purge -> /login      | purge      |
 *
 * "Preauth only -> the TOTP step, not `/login`" is the row most likely to be got wrong by
 * reflex, and it matters: step one is already done, and sending the staff member back to a
 * password form would make them redo it (burning a Turnstile token and a throttle slot) for
 * no reason.
 *
 * An EXPIRED preauth needs no row of its own by construction: the cookie's Max-Age matches
 * the token's lifetime, so the browser stops sending it and the state collapses into "none".
 * If a stale one does arrive, the backend 401s and the caller clears it (see `lib/session.ts`).
 */
import { DEFAULT_NEXT, safeNext } from "@/lib/next-param";

export const LOGIN_PATH = "/login";
export const TOTP_PATH = "/totp";
export const DASHBOARD_PATH = "/";
export const ACCEPT_INVITE_PATH = "/accept-invite";
export const REFRESH_REDIRECT_PATH = "/api/auth/refresh-redirect";

/**
 * Where a purge decision SENDS a page, rather than where it ends up.
 *
 * A Server Component may read cookies but never write them, so the page that notices the
 * anomaly cannot be the thing that clears it — `jar.delete()` throws during RSC render,
 * which is a 500, not a redirect. (Measured: `/login` carrying the anomaly answered 500
 * before this indirection existed.) The page therefore redirects to a Route Handler that
 * clears the three cookies and sends the browser on to `/login`.
 *
 * BFF routes ignore this value: they can write cookies themselves, so they purge in place
 * and answer 401.
 */
export const PURGE_PATH = "/api/auth/purge";

export interface AdminCookies {
  access?: string;
  refresh?: string;
  preauth?: string;
}

/**
 * `public`  — the accept-invite page. Reachable with any cookie state, because the proof
 *             it consumes is the invite token in the URL, not a session.
 * `login`   — the password step.
 * `totp`    — the second-factor step; the only place a preauth token is useful.
 * `app`     — every real admin page.
 * `bff`     — this app's own Route Handlers, which answer with status codes, not redirects.
 */
export type RouteClass = "public" | "login" | "totp" | "app" | "bff";

export type CookieState = "none" | "preauth" | "session" | "anomaly";

export type AuthDecision =
  /** Render this route. */
  | { kind: "allow" }
  /** Proceed with this access token. */
  | { kind: "authenticated"; token: string }
  /** Page route: the access token is gone but the session is not — bounce through the
   *  renewal Route Handler, which is allowed to persist the rotated pair. */
  | { kind: "refresh"; to: string }
  /** BFF route: same situation, but the caller may write cookies itself, so it renews
   *  inline rather than bouncing a fetch through a redirect. */
  | { kind: "renew" }
  /** BFF route with nothing usable. 401; do NOT reach for whatever other token exists. */
  | { kind: "unauthenticated" }
  /** Wrong route for this state. */
  | { kind: "redirect"; to: string }
  /** Clear all three cookies, then go. `to` is the purge Route Handler for pages; BFF
   *  routes ignore it and purge in place. */
  | { kind: "purge"; to: string };

/**
 * Presence only — never a decode. The BFF must not hold Django's signing key, so any claim
 * it read out of a token would be unverified, and an unverified claim treated as
 * authoritative is worse than no claim at all.
 *
 * A preauth cookie alongside EITHER half of the session pair is the anomaly, not just
 * alongside both: `lib/admin-session.ts` clears the whole opposing set on every write, so
 * a single stray half is exactly as impossible as two.
 */
export function cookieState(c: AdminCookies): CookieState {
  const hasPreauth = Boolean(c.preauth);
  const hasSession = Boolean(c.access || c.refresh);
  if (hasPreauth && hasSession) return "anomaly";
  if (hasPreauth) return "preauth";
  if (hasSession) return "session";
  return "none";
}

/** Exact-segment matching, so `/login-help` is an app route and not the login page. */
export function routeClassFor(pathname: string): RouteClass {
  const path = pathname.split("?")[0];
  if (isSegment(path, LOGIN_PATH)) return "login";
  if (isSegment(path, ACCEPT_INVITE_PATH)) return "public";
  if (isSegment(path, TOTP_PATH)) return "totp";
  if (isSegment(path, "/api")) return "bff";
  return "app";
}

function isSegment(pathname: string, base: string): boolean {
  return pathname === base || pathname.startsWith(`${base}/`);
}

/** Build a "come back here afterwards" URL, with the target sanitised first. */
export function withNext(base: string, currentPath: string): string {
  return `${base}?next=${encodeURIComponent(safeNext(currentPath, DEFAULT_NEXT))}`;
}

export function decideAuth(
  cookies: AdminCookies,
  routeClass: RouteClass,
  currentPath: string,
): AuthDecision {
  const state = cookieState(cookies);

  // Fail-closed first. Deliberately BEFORE the route switch so no route class can be
  // exempted from it by a later edit — including `public`, whose page needs no cookies
  // and therefore loses nothing by having a broken set thrown away.
  if (state === "anomaly") return { kind: "purge", to: PURGE_PATH };

  if (routeClass === "public") return { kind: "allow" };

  if (routeClass === "bff") {
    if (state === "session") {
      return cookies.access
        ? { kind: "authenticated", token: cookies.access }
        : { kind: "renew" };
    }
    // "none" and "preauth" alike. THE point of this branch: a preauth cookie is not a
    // fallback credential, and a helper that reached for "whichever token cookie exists"
    // would forward a bootstrap token to endpoints it was defined never to open.
    return { kind: "unauthenticated" };
  }

  if (routeClass === "login") {
    if (state === "preauth") return { kind: "redirect", to: TOTP_PATH };
    if (state === "session") return { kind: "redirect", to: DASHBOARD_PATH };
    return { kind: "allow" };
  }

  if (routeClass === "totp") {
    if (state === "preauth") return { kind: "allow" };
    if (state === "session") return { kind: "redirect", to: DASHBOARD_PATH };
    // No preauth token means there is nothing here to do — and no `?next=`, because
    // "come back to the TOTP step afterwards" is never what anyone wants.
    return { kind: "redirect", to: LOGIN_PATH };
  }

  // routeClass === "app"
  if (state === "preauth") return { kind: "redirect", to: TOTP_PATH };
  if (state === "none") return { kind: "redirect", to: withNext(LOGIN_PATH, currentPath) };
  return cookies.access
    ? { kind: "authenticated", token: cookies.access }
    : { kind: "refresh", to: withNext(REFRESH_REDIRECT_PATH, currentPath) };
}
