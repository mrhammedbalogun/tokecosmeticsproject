/**
 * Single source of truth for the admin app's session cookies.
 *
 * THREE COOKIES, NOT TWO, and the third one is the whole design (Plan-16 Task 5 ruling).
 * The staff login is a ceremony of three steps — password+Turnstile, then a TOTP factor,
 * and only then a session — so between step 1 and step 3 the browser holds a credential
 * that is emphatically NOT a session: the ten-minute preauth token from
 * `apps/accounts/authentication.mint_preauth_token`, which opens exactly three backend
 * endpoints and nothing else.
 *
 * WHY IT IS A COOKIE AND NOT FORM STATE. A Server Function's returned state travels to
 * the browser inside the RSC payload; putting a bearer credential there puts it in the
 * client payload, in the DOM, and in whatever the browser caches. httpOnly is the whole
 * point of the storefront's cookie dance and the preauth token deserves it more, not
 * less.
 *
 * WHY A DISTINCT NAME AND NOT `admin_access`. Sharing one cookie would force the gate to
 * discriminate by DECODING the token's `toke_aud` claim — and the BFF cannot verify that
 * claim, because it must never hold Django's signing key. An unverified decode that the
 * gate then treats as authoritative is the declaration-versus-behaviour trap in fresh
 * paint. Distinct names let the gate discriminate on PRESENCE alone, which is a fact it
 * can actually establish.
 *
 * MUTUAL EXCLUSIVITY IS ENFORCED AT WRITE TIME, in `lib/admin-session.ts`: the function
 * that stores a preauth token clears the session pair, and the one that stores the pair
 * (TOTP confirm, the only place the backend mints one) clears the preauth. No legitimate
 * request can carry both — which is what turns "both present" into a detectable anomaly
 * rather than an ambiguity the gate has to guess its way out of.
 *
 * SameSite=STRICT on all three, where the storefront uses Lax. The storefront needs Lax
 * because customers arrive on gated pages from emails and search results; nothing legitimate
 * enters the admin from another origin. The one inbound link that exists — the staff invite
 * email pointing at `/accept-invite?token=` — is a PUBLIC route that reads no cookie, so
 * Strict costs nothing here and removes a whole class of cross-site request.
 */
export const ACCESS_COOKIE = "admin_access";
export const REFRESH_COOKIE = "admin_refresh";
export const PREAUTH_COOKIE = "admin_preauth";

/**
 * ADMIN LIFETIMES ARE DELIBERATELY SHORTER THAN THE STOREFRONT'S, and the refresh is
 * shorter by three orders of magnitude (12 hours against 14 days).
 *
 * A customer session that survives a fortnight is a convenience decision about a low-value
 * credential. A staff session that survived a fortnight would mean the TOTP factor is
 * proved once and then trusted for two weeks — which is most of what a second factor is
 * for, given away. A daily re-ceremony is the correct cost for a credential that can edit
 * the payout bank account, and it also bounds the value of a stolen laptop to one working
 * day.
 *
 * Both MUST expire no later than the tokens they carry (backend SIMPLE_JWT: access 15 min,
 * refresh 30 days). The access cookie is 10 minutes against a 15-minute token — the slack
 * covers clock skew between the browser and the API, and it is what stops the app from
 * confidently presenting a credential Django has already rejected.
 */
export const ACCESS_MAX_AGE = 60 * 10; // 10 min, under the 15-min access token
export const REFRESH_MAX_AGE = 60 * 60 * 12; // 12 h, well under the 30-day token

/**
 * Matched to `authentication.PREAUTH_TOKEN_LIFETIME` (10 minutes) ON PURPOSE. The cookie
 * expiring at the same moment the token does is what makes "expired preauth" collapse into
 * the "no cookies" row of the gate matrix instead of being a fourth state: the browser
 * simply stops sending it. A stale one that does arrive (clock skew, a cookie restored by
 * a session-restore feature) is refused by the backend, and the BFF clears it there.
 */
export const PREAUTH_MAX_AGE = 60 * 10;

export interface CookieOptions {
  httpOnly: boolean;
  sameSite: "strict";
  secure: boolean;
  path: string;
  maxAge?: number;
}

export function cookieOptions(
  opts: { nodeEnv?: string; maxAge?: number } = {},
): CookieOptions {
  const env = opts.nodeEnv ?? process.env.NODE_ENV;
  return {
    httpOnly: true,
    sameSite: "strict",
    // `secure` off in development only, so http://localhost:3001 still receives them.
    secure: env === "production",
    path: "/",
    ...(opts.maxAge !== undefined ? { maxAge: opts.maxAge } : {}),
  };
}
