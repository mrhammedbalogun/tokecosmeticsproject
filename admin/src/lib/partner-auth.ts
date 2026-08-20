/**
 * Cookie constants for the delivery-partner portal (Plan-39) — `/partner/*`.
 *
 * A THIRD credential pair, deliberately not `admin_*`: the portal's whole security
 * story mirrors the admin app's (httpOnly, SameSite=Strict, presence-discriminated,
 * never decoded by the BFF), but the tokens carry the `toke-partner` audience and the
 * two sets must never be confusable — distinct names let `proxy.ts` route the two
 * populations on PRESENCE alone, the only fact it can establish.
 *
 * Same lifetimes as the admin pair. The partner login has no second factor (plan-39
 * ruling), which is an argument for SHORTER sessions, not longer: a 12-hour refresh
 * bounds a stolen credential to one working day, same as staff.
 *
 * CONSTANTS ONLY in this file — `proxy.ts` imports it, and the proxy must stay
 * dependency-free (see the rule at the top of that file).
 */
export const PARTNER_ACCESS_COOKIE = "partner_access";
export const PARTNER_REFRESH_COOKIE = "partner_refresh";

export const PARTNER_ACCESS_MAX_AGE = 60 * 10; // 10 min, under the 15-min token
export const PARTNER_REFRESH_MAX_AGE = 60 * 60 * 12; // 12 h, well under the 30-day token

export const PARTNER_LOGIN_PATH = "/partner/login";
export const PARTNER_HOME_PATH = "/partner";
