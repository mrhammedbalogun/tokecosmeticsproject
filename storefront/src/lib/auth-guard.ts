/**
 * The account-area gate: given the two session cookies, decide what happens next.
 *
 * Kept PURE and separate from the redirect that acts on it. `redirect()` throws
 * NEXT_REDIRECT, so folding the decision into it would mean the interesting logic —
 * which of three routes we take — could only be observed through thrown control flow.
 *
 * WHY A "refresh" OUTCOME EXISTS. Server Components may READ cookies but never WRITE
 * them (Next 16, `01-app/03-api-reference/04-functions/cookies.md`: "Setting cookies is
 * not supported during Server Component rendering"). The backend runs SimpleJWT with
 * ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION, so a refresh yields a NEW pair that
 * MUST be persisted or the session dies. Persisting is only legal in a Route Handler.
 * Hence an expired access token cannot be renewed where it is noticed; the user is sent
 * through a Route Handler that renews and returns them to where they were going.
 *
 * WHY NOT GATE ON THE ACCESS COOKIE ALONE: it lives 30 minutes while refresh lives 14
 * days. Treating "no access" as "logged out" would spuriously log a user out twice an
 * hour. See also the presence check in src/proxy.ts, which gates on refresh for the
 * same reason.
 */
import { DEFAULT_NEXT, safeNext } from "@/lib/next-param";

export const REFRESH_REDIRECT_PATH = "/api/auth/refresh-redirect";
export const LOGIN_PATH = "/login";

export type AuthDecision =
  | { kind: "authenticated"; token: string }
  | { kind: "login"; to: string }
  | { kind: "refresh"; to: string };

/**
 * Build a "come back here afterwards" URL. Exported so Route Handlers that redirect to
 * login (see api/orders/[number]/invoice) share ONE encoding of `?next=` with the
 * decisions below, rather than each hand-rolling a string that only mostly matches.
 */
export function withNext(base: string, currentPath: string): string {
  // safeNext even though we normally build currentPath ourselves: this value is about to
  // become a redirect target, and "it's trusted at every call site today" is exactly the
  // assumption that turns into an open redirect two plans from now.
  const next = safeNext(currentPath, DEFAULT_NEXT);
  return `${base}?next=${encodeURIComponent(next)}`;
}

export function decideAuth(
  access: string | undefined,
  refresh: string | undefined,
  currentPath: string,
): AuthDecision {
  if (access) return { kind: "authenticated", token: access };
  if (refresh) return { kind: "refresh", to: withNext(REFRESH_REDIRECT_PATH, currentPath) };
  return { kind: "login", to: withNext(LOGIN_PATH, currentPath) };
}

export type LoginEntry =
  | { kind: "go"; to: string }
  | { kind: "renew"; to: string }
  | { kind: "form" };

/**
 * What the LOGIN PAGE should do for a visitor who already carries session cookies.
 *
 * A DIFFERENT QUESTION FROM `decideAuth`, which is why it is a different function.
 * `decideAuth` answers "may this request proceed?" for a gated page — there an access
 * token alone is enough, because the page is about to try a fetch that will tell the
 * truth. The login page answers "should I skip the form?", and there an access cookie
 * alone is NOT enough:
 *
 * `src/proxy.ts:40` redirects `/account*` to `/login` whenever the REFRESH cookie is
 * absent. So skipping the form for an access-only visitor sends them to `/account`, the
 * proxy sends them back to `/login`, and the page skips the form again — an infinite
 * redirect with no API call anywhere in it to break the cycle. Both cookies, or a form.
 *
 * `renew` exists to heal the rotation race: the loser of a concurrent refresh
 * (ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION) arrives holding a live refresh and
 * no access. Asking that visitor for a password is precisely the bug being fixed. If the
 * renewal itself fails, `api/auth/refresh-redirect/route.ts` clears BOTH cookies before
 * returning here — which is what guarantees this terminates in a form rather than a loop.
 */
export function decideLoginEntry(
  access: string | undefined,
  refresh: string | undefined,
  next: string,
): LoginEntry {
  const to = safeNext(next, DEFAULT_NEXT);
  if (access && refresh) return { kind: "go", to };
  if (refresh) return { kind: "renew", to: withNext(REFRESH_REDIRECT_PATH, next) };
  return { kind: "form" };
}
