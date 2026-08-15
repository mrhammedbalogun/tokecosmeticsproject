/**
 * Referral attribution: the cookie, and the rules around it.
 *
 * Constants only, no behaviour — `proxy.ts` imports from here and the proxy must stay
 * dependency-free (see its own note: it may be deployed to the CDN edge, separate from
 * render code, so it may only import cookie-name constants, never modules with real
 * behaviour). This file is exactly that kind of module and nothing more.
 */

/** The query parameter a referrer's link carries: `https://…/?ref=AMINA7K3P`. Must match
 * what the backend builds in `referrals/views.py::_share_url` — the two are the same
 * contract seen from opposite ends. */
export const REFERRAL_PARAM = "ref";

/** httpOnly, so page JavaScript cannot read or forge it. That is not paranoia about the
 * visitor: it means the ONLY thing that can put a code in front of the checkout API is
 * this proxy, having actually seen a `?ref=` on a real navigation. */
export const REFERRAL_COOKIE = "tc_ref";

/**
 * 30 days — the published tracking window ("we honor a 30-day tracking window, ensuring
 * you get credit for sales made long after the first click").
 *
 * MUST MATCH `settings.REFERRAL_COOKIE_DAYS` on the backend. They are two halves of one
 * promise: this is how long the browser keeps the code, that is what the account page
 * tells the referrer the window is. If they drift, the shop advertises one number and
 * pays on another.
 */
export const REFERRAL_COOKIE_DAYS = 30;
export const REFERRAL_COOKIE_MAX_AGE = 60 * 60 * 24 * REFERRAL_COOKIE_DAYS;

/**
 * A code is uppercase A-Z and 2-9, 5 to 32 characters (a name stem plus four random
 * characters — see `referrals/services.py::_candidate_code`).
 *
 * Validated in the proxy BEFORE anything is stored, because the value arrives from a URL
 * anyone can craft and is later written into a JSON body sent to the API. Nothing
 * downstream interpolates it into SQL or HTML, so this is not the control that stops an
 * injection — it is the control that stops the cookie jar becoming a place to park
 * arbitrary attacker-chosen strings, and that keeps the checkout payload's shape
 * predictable. An unrecognised code is dropped silently: a visitor who mistyped a link
 * should get the shop, not an error.
 */
const CODE_PATTERN = /^[A-Z2-9]{5,32}$/;

export function normalizeReferralCode(raw: string | null | undefined): string {
  if (!raw) return "";
  const code = raw.trim().toUpperCase();
  return CODE_PATTERN.test(code) ? code : "";
}

/**
 * LAST-CLICK WINS, stated once so it can be pointed at in a dispute.
 *
 * A visitor who arrives on Amina's link, browses, then arrives again on Chidi's link is
 * credited to Chidi. The published terms are silent on this, so it needed deciding
 * rather than emerging: last-click is what affiliate networks do by default, it is the
 * easier rule to explain ("the last link they used before buying"), and it rewards the
 * post that actually converted. The alternative — first-touch — would mean a referrer
 * keeps a customer for 30 days no matter who else's work brings them back, which is the
 * version people argue about.
 *
 * Mechanically this is just "the proxy overwrites the cookie whenever it sees a valid
 * ?ref", which also refreshes the 30 days from the newest click.
 */
export const ATTRIBUTION_RULE = "last-click" as const;
