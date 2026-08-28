import { cookies } from "next/headers";
import { ApiError, apiFetch } from "@/lib/api";
import { ACCESS_COOKIE } from "@/lib/auth";
import { getReferralTerms } from "@/lib/referral-terms";
import {
  REFERRAL_COOKIE,
  REFERRAL_COOKIE_MAX_AGE,
  normalizeReferralCode,
} from "@/lib/referral";

/**
 * Apply a referral code somebody typed in, and report whose it is.
 *
 * ── WHY THIS SETS A COOKIE RATHER THAN RETURNING A CODE TO THE CLIENT ────────────
 *
 * The checkout BFF reads attribution from the httpOnly `tc_ref` cookie and explicitly
 * DISCARDS any `referral_code` in its request body — that is what stops a customer
 * crediting an arbitrary referrer (or a second account of their own) from devtools. A
 * manual-entry field must not become the hole in that: so this route validates upstream
 * and writes the same httpOnly cookie the proxy writes for `?ref=`. The browser still
 * never gets to name who is paid; it only gets to ask.
 *
 * The cookie is written on the RESPONSE rather than through the `cookies()` jar for the
 * same reason the proxy does: a Route Handler may set cookies, and doing it explicitly
 * here keeps the flags (httpOnly, lax, 30 days) in one shape with `proxy.ts`.
 *
 * GET would have been wrong: this mutates state (it re-points 30 days of attribution),
 * so it is a POST. NOTE the honest limit of that: Next's Origin/Host CSRF check covers
 * Server ACTIONS only — a Route Handler like this one gets no such protection, and
 * `req.json()` parses a cross-site text/plain form POST happily. Acceptable HERE
 * because any site can already set a visitor's attribution with a top-level `?ref=`
 * link (that is the product), so this route grants a cross-site caller nothing new.
 * If it ever does more than apply a validated code — clearing the cookie, accepting
 * any other mutation — it needs its own origin check first.
 */
function json(data: unknown, status = 200, cookie?: string) {
  const headers = new Headers({ "content-type": "application/json" });
  if (cookie) headers.append("set-cookie", cookie);
  return new Response(JSON.stringify(data), { status, headers });
}

function referralCookie(code: string): string {
  const secure = process.env.NODE_ENV === "production" ? "; Secure" : "";
  return (
    `${REFERRAL_COOKIE}=${code}; Path=/; Max-Age=${REFERRAL_COOKIE_MAX_AGE}` +
    `; HttpOnly; SameSite=Lax${secure}`
  );
}

type Lookup = {
  valid: boolean;
  reason?: string;
  referrer_name?: string;
  /** The referred customer's discount, as a percentage string. Added to this response
   *  (2026-08-27) rather than passed down through props so the field can say what the
   *  shopper ACTUALLY gets — an Owner may have set it to 0 on the admin's Business
   *  Decisions page, and a message promising money off is worse than no message. It
   *  comes from the same `/referrals/terms/` values /affiliates advertises. */
  customer_discount_percent?: string;
};

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const code = normalizeReferralCode(typeof body.code === "string" ? body.code : "");
  if (!code) {
    return json({ valid: false, reason: "not_found" }, 200);
  }

  // Forwarded when present so the backend can recognise a customer entering their OWN
  // code and say so, instead of cheerfully confirming a link that will never pay them.
  // Read-only: `apiFetch`, not `fetchWithAuth`, because a stale access token here should
  // just mean "we could not tell it was you", never a token refresh on a public lookup.
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;

  try {
    const raw = await apiFetch<Lookup>(
      `/referrals/lookup/?code=${encodeURIComponent(code)}`,
      { token, cache: "no-store" },
    );
    // PROJECTED, never passed through: the "first-name-level only" guarantee must hold
    // even if the backend serializer grows a field for some other consumer — this
    // response goes to anonymous browsers.
    const out: Lookup = { valid: raw.valid === true };
    if (raw.reason !== undefined) out.reason = raw.reason;
    if (raw.referrer_name !== undefined) out.referrer_name = raw.referrer_name;
    if (!out.valid) {
      // No cookie written — a wrong code must not silently replace attribution the
      // visitor already has from a link they really did click.
      return json(out, 200);
    }
    // Best effort, and deliberately so: the code IS valid and the cookie IS being
    // written, so a terms lookup that fails must not turn a successful apply into a
    // failed one. The field falls back to wording that promises no amount.
    out.customer_discount_percent = await getReferralTerms()
      .then((t) => t.customer_discount_percent)
      .catch(() => undefined);
    return json(out, 200, referralCookie(code));
  } catch (e) {
    if (e instanceof ApiError) {
      // 429 from the lookup throttle is the one a customer could plausibly meet.
      return json({ valid: false, reason: e.status === 429 ? "rate_limited" : "error" }, 200);
    }
    return json({ valid: false, reason: "error" }, 200);
  }
}
