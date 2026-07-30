/**
 * The three-step staff ceremony, and the ONLY place admin cookies are written.
 *
 * ── THE CEREMONY, BECAUSE THE ENDPOINT NAMES NO LONGER DESCRIBE IT ────────────────
 *
 * 1. `POST /auth/admin-token/` — password + Turnstile. Despite its name it mints **no
 *    session**: it returns a ten-minute PREAUTH token and nothing else, whether or not
 *    the caller has TOTP enrolled. One bootstrap path, not two.
 * 2. That preauth token opens **exactly three** backend endpoints: TOTP enrol, TOTP
 *    confirm, recovery-code verification. Everything else 401s, enforced in Django by
 *    `CustomerJWTAuthentication` (the project default, which refuses preauth tokens) and
 *    `AdminJWTAuthentication` (which accepts only the completed-ceremony audience).
 * 3. `POST /auth/admin-totp/confirm/` is the only place an admin token pair exists.
 *
 * Accepting a staff invite enters at the same place: it returns a preauth token too.
 *
 * ── MUTUAL EXCLUSIVITY IS ENFORCED HERE, AT WRITE TIME ────────────────────────────
 *
 * `storePreauth` clears the session pair; `storeSession` clears the preauth. That is what
 * makes "both cookies present" a state no legitimate request can produce — and therefore
 * something the gate can treat as an anomaly and purge, instead of a genuine ambiguity it
 * would have to resolve by guessing (or, worse, by decoding a token it cannot verify).
 *
 * ── WHAT WAS DELIBERATELY NOT PORTED FROM THE STOREFRONT ──────────────────────────
 *
 * The guest-cart merge, account claiming, and Turnstile-proof session minting. They have
 * no admin analogue, and dead ported code on this origin is attack surface with no
 * constituency. The BFF surface here is meant to stay countable on one hand.
 *
 * Every function takes the cookie jar explicitly rather than calling `cookies()` itself:
 * it keeps them testable without mocking `next/headers`, and it puts the "must run
 * somewhere cookie writes are legal" requirement in plain sight at every call site.
 */
import type { cookies } from "next/headers";
import { apiFetch } from "@/lib/api";
import {
  ACCESS_COOKIE,
  ACCESS_MAX_AGE,
  PREAUTH_COOKIE,
  PREAUTH_MAX_AGE,
  REFRESH_COOKIE,
  REFRESH_MAX_AGE,
  cookieOptions,
} from "@/lib/auth";

export type Jar = Awaited<ReturnType<typeof cookies>>;

/** Store the bootstrap credential. Clears any session pair, unconditionally. */
export function storePreauth(jar: Jar, token: string): void {
  jar.delete(ACCESS_COOKIE);
  jar.delete(REFRESH_COOKIE);
  jar.set(PREAUTH_COOKIE, token, cookieOptions({ maxAge: PREAUTH_MAX_AGE }));
}

/** Store a real admin session. Clears the preauth cookie, unconditionally. */
export function storeSession(jar: Jar, access: string, refresh?: string): void {
  jar.delete(PREAUTH_COOKIE);
  jar.set(ACCESS_COOKIE, access, cookieOptions({ maxAge: ACCESS_MAX_AGE }));
  if (refresh) {
    jar.set(REFRESH_COOKIE, refresh, cookieOptions({ maxAge: REFRESH_MAX_AGE }));
  }
}

/** Throw the whole set away. Used by sign-out, by a failed renewal, and by the gate's
 *  anomaly row. */
export function clearSession(jar: Jar): void {
  jar.delete(ACCESS_COOKIE);
  jar.delete(REFRESH_COOKIE);
  jar.delete(PREAUTH_COOKIE);
}

export interface TurnstileOpts {
  /** The widget token (`cf-turnstile-response`). Forwarded to Django as
   *  `turnstile_token`; omitted entirely when absent so a gate-off deployment keeps the
   *  exact old request shape. Verification lives in Django — the API is reachable
   *  directly, so a BFF-side check would be decorative. */
  turnstileToken?: string;
}

function withTurnstile(
  body: Record<string, unknown>,
  opts: TurnstileOpts,
): Record<string, unknown> {
  return opts.turnstileToken ? { ...body, turnstile_token: opts.turnstileToken } : body;
}

/**
 * The BFF shared-secret header, for the two endpoints whose only legitimate caller is
 * this app. See `backend/apps/accounts/bff.py` for the full reasoning.
 *
 * IT IS NOT AUTHENTICATION and must never be described as such — it is an anti-abuse
 * gate that makes junk cost Django a string compare instead of an outbound Turnstile
 * siteverify call. Everything that actually protects the endpoint (Turnstile, the
 * password, TOTP, the audience claim) is unchanged.
 *
 * SERVER-SIDE ONLY, and that is load-bearing rather than incidental: `ADMIN_BFF_SECRET`
 * has no `NEXT_PUBLIC_` prefix, so Next will not inline it into a client bundle. It may
 * only ever be read from a Server Function or Route Handler — which is exactly where
 * these two calls already live.
 *
 * OMITTED, not blank, when unset. Django treats absent and empty the same, but sending
 * an empty header asserts there is a secret and it happens to be nothing. It also keeps
 * a gate-off deployment byte-identical to the old request shape.
 *
 * Applied to exactly two calls. Adding it to the TOTP calls would widen the secret's
 * exposure for no gain — those carry a preauth token, which is a real credential.
 */
function bffHeaders(): Record<string, string> {
  const secret = process.env.ADMIN_BFF_SECRET;
  return secret ? { "X-Admin-BFF-Secret": secret } : {};
}

export interface PreauthResponse {
  preauth_token: string;
  expires_in: number;
  /** Which screen to draw next. NOT a branch in the security logic — the backend returns
   *  the same kind of token either way. */
  totp_enrolled?: boolean;
}

/**
 * Step one. Returns the preauth response so the caller knows whether to send the staff
 * member to enrolment or to a code prompt.
 *
 * Cookie-writing context only (Route Handler or Server Function).
 */
export async function adminLogin(
  jar: Jar,
  credentials: { email: string; password: string },
  opts: TurnstileOpts = {},
): Promise<PreauthResponse> {
  const out = await apiFetch<PreauthResponse>("/auth/admin-token/", {
    method: "POST",
    body: withTurnstile(credentials, opts),
    headers: bffHeaders(),
  });
  storePreauth(jar, out.preauth_token);
  return out;
}

export interface EnrolResponse {
  secret: string;
  provisioning_uri: string;
  issuer: string;
}

/**
 * Step two, first half. Writes no cookie — the preauth token it authenticates with is
 * already in the jar and is unchanged by this call.
 *
 * The response carries the TOTP secret, so it must never be logged, never persisted and
 * never sent anywhere but straight to the screen of the person who just proved a password.
 */
export async function enrolTotp(preauthToken: string): Promise<EnrolResponse> {
  return apiFetch<EnrolResponse>("/auth/admin-totp/enrol/", {
    method: "POST",
    token: preauthToken,
  });
}

export interface ConfirmResponse {
  access: string;
  refresh: string;
  /** Present ONLY on the response that confirms a new enrolment. Shown once, never again
   *  and never stored. */
  recovery_codes?: string[];
}

/**
 * Step three — the only call in this app that can produce a session.
 *
 * Cookie-writing context only.
 */
export async function confirmTotp(
  jar: Jar,
  preauthToken: string,
  code: string,
): Promise<ConfirmResponse> {
  const out = await apiFetch<ConfirmResponse>("/auth/admin-totp/confirm/", {
    method: "POST",
    token: preauthToken,
    body: { code },
  });
  storeSession(jar, out.access, out.refresh);
  return out;
}

export interface RecoveryResponse {
  detail: string;
  enrolment_required: boolean;
}

/**
 * The lost-device path. Burns one recovery code, which VOIDS the enrolment and the
 * remaining codes — and mints nothing. The preauth cookie deliberately survives: the
 * staff member is sent straight back to enrolment with the same bootstrap credential,
 * which is the whole reason the backend can keep "only TOTP-confirm mints" literal.
 */
export async function recoverTotp(
  preauthToken: string,
  code: string,
): Promise<RecoveryResponse> {
  return apiFetch<RecoveryResponse>("/auth/admin-totp/recovery/", {
    method: "POST",
    token: preauthToken,
    body: { code },
  });
}

/**
 * The invite-acceptance entry point. Public — the person accepting has no session, and
 * the proof they present is the token from their inbox.
 *
 * It lands them in exactly the same place as a password login: holding a preauth token,
 * owing a second factor. Cookie-writing context only.
 */
export async function acceptInvite(
  jar: Jar,
  payload: { token: string; password: string },
  opts: TurnstileOpts = {},
): Promise<PreauthResponse & { detail?: string }> {
  const out = await apiFetch<PreauthResponse & { detail?: string }>(
    "/admin/staff/invites/accept/",
    { method: "POST", body: withTurnstile({ ...payload }, opts), headers: bffHeaders() },
  );
  storePreauth(jar, out.preauth_token);
  return out;
}

/**
 * Sign out: blacklist the refresh token server-side, then drop every cookie.
 *
 * The blacklist call is REAL revocation, not a gesture: `rest_framework_simplejwt.
 * token_blacklist` is in INSTALLED_APPS, so `/auth/logout/` genuinely kills the refresh
 * token. The 10-minute access token is not revocable and survives until it expires —
 * which is the honest reason admin access lifetime is 10 minutes and not an hour.
 *
 * Best-effort, in this order and deliberately: the cookies are cleared even if the
 * backend call fails, because a sign-out button that leaves a session cookie behind
 * because the network hiccuped is the worst possible failure mode for this control.
 */
export async function adminLogout(jar: Jar): Promise<void> {
  const access = jar.get(ACCESS_COOKIE)?.value;
  const refresh = jar.get(REFRESH_COOKIE)?.value;
  clearSession(jar);
  if (!access || !refresh) return;
  try {
    await apiFetch("/auth/logout/", { method: "POST", token: access, body: { refresh } });
  } catch {
    // Swallowed: the local session is already gone, and surfacing a backend error here
    // would tell the user the sign-out failed when the part that matters succeeded.
  }
}
