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
  DEVICE_COOKIE,
  DEVICE_MAX_AGE,
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
 *  anomaly row. The DEVICE cookie deliberately survives: it is a second factor, not
 *  session state, and signing out is not the same act as un-trusting the browser —
 *  see the `DEVICE_COOKIE` docstring in `lib/auth.ts`. */
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

export type SecondFactorMethod = "totp" | "email";

export interface PreauthResponse {
  preauth_token: string;
  expires_in: number;
  /** Which screen to draw next. NOT a branch in the security logic — the backend returns
   *  the same kind of token either way. */
  totp_enrolled?: boolean;
  /** The method this account confirmed, or null for "none chosen yet" (the chooser
   *  screen). Same UI-hint status as `totp_enrolled`, which it supersedes. */
  second_factor?: SecondFactorMethod | null;
  /** True when the forwarded device cookie matched a live trust row: the login action
   *  may go straight to a trusted-device confirm. A HINT — the confirm endpoint
   *  re-runs the same check before anything is minted. */
  device_trusted?: boolean;
}

/**
 * Step one. Returns the preauth response so the caller knows whether to send the staff
 * member to the method chooser, a code prompt, or straight through on a trusted device.
 *
 * The device cookie rides along when the browser holds one; Django answers with
 * `device_trusted` and nothing else changes. Cookie-writing context only (Route
 * Handler or Server Function).
 */
export async function adminLogin(
  jar: Jar,
  credentials: { email: string; password: string },
  opts: TurnstileOpts = {},
): Promise<PreauthResponse> {
  const deviceToken = jar.get(DEVICE_COOKIE)?.value;
  const out = await apiFetch<PreauthResponse>("/auth/admin-token/", {
    method: "POST",
    body: withTurnstile(
      deviceToken ? { ...credentials, device_token: deviceToken } : { ...credentials },
      opts,
    ),
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
  /** Present ONLY when `trust_device` was asked for alongside a real code. Goes
   *  straight into the httpOnly device cookie and nowhere else. */
  device_token?: string;
  device_expires_in?: number;
}

export interface ConfirmOptions {
  /** Defaults to "totp" — the shape every pre-Plan-33 caller sent. */
  method?: SecondFactorMethod | "trusted_device";
  code?: string;
  /** Ask Django for a 30-day trust token alongside the session. Honoured only on the
   *  coded methods; a trusted device can never mint fresh trust. */
  trustDevice?: boolean;
}

/**
 * Step three — the only call in this app that can produce a session.
 *
 * One function for all three methods because the backend has one endpoint and one
 * mint, and mirroring that here keeps "the only call that can produce a session"
 * literally true. The trusted-device method reads the device cookie itself; a granted
 * trust token is written back to the same cookie. A REFUSED trusted-device redemption
 * deletes the cookie — the backend has voted it dead (expired, revoked, or another
 * user's), and re-presenting it every login would fail forever.
 *
 * Cookie-writing context only.
 */
export async function confirmSecondFactor(
  jar: Jar,
  preauthToken: string,
  opts: ConfirmOptions,
): Promise<ConfirmResponse> {
  const method = opts.method ?? "totp";
  const body: Record<string, unknown> = { method };
  if (opts.code !== undefined) body.code = opts.code;
  if (opts.trustDevice) body.trust_device = true;
  if (method === "trusted_device") {
    body.device_token = jar.get(DEVICE_COOKIE)?.value ?? "";
  }
  let out: ConfirmResponse;
  try {
    out = await apiFetch<ConfirmResponse>("/auth/admin-totp/confirm/", {
      method: "POST",
      token: preauthToken,
      body,
    });
  } catch (e) {
    if (method === "trusted_device") jar.delete(DEVICE_COOKIE);
    throw e;
  }
  storeSession(jar, out.access, out.refresh);
  if (out.device_token) {
    jar.set(
      DEVICE_COOKIE,
      out.device_token,
      cookieOptions({ maxAge: out.device_expires_in ?? DEVICE_MAX_AGE }),
    );
  }
  return out;
}

export interface EmailOTPRequestResponse {
  detail: string;
  /** 0 = a fresh code was just sent; >0 = one is already in flight, sent that many
   *  seconds into its 60-second cooldown. */
  retry_after: number;
  expires_in: number;
}

/**
 * Ask Django to mail a sign-in code to the preauth token's own user. Writes no
 * cookie; safe to call from a render-adjacent action because a repeat inside the
 * cooldown is a 200 that sends nothing.
 */
export async function requestEmailOtp(
  preauthToken: string,
): Promise<EmailOTPRequestResponse> {
  return apiFetch<EmailOTPRequestResponse>("/auth/admin-email-otp/request/", {
    method: "POST",
    token: preauthToken,
  });
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
