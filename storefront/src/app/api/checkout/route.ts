import { cookies } from "next/headers";
import { randomUUID } from "node:crypto";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import {
  ACCESS_COOKIE,
  GUEST_ORDER_COOKIE,
  GUEST_ORDER_MAX_AGE,
  REFRESH_COOKIE,
  cookieOptions,
} from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { REFERRAL_COOKIE, normalizeReferralCode } from "@/lib/referral";

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

/** Place order (Plan-14; guests since Plan-38). Generates the Idempotency-Key
 * server-side when the client didn't. Bank-transfer details ride back in
 * payment.data.
 *
 * Guest requests (no session cookies) carry guest_email/guest_phone + an inline
 * address + turnstile_token; the backend validates all of it. On the guest 201 the
 * `guest_order_token` is moved into an httpOnly cookie and STRIPPED from the browser
 * response — it is the guest's only credential for the confirmation page and payment
 * verify, and page JS must never be able to read it (XSS). */
export async function POST(req: Request) {
  const jar = await cookies();
  const isGuest = !jar.get(ACCESS_COOKIE)?.value && !jar.get(REFRESH_COOKIE)?.value;
  const body = await req.json().catch(() => ({}));
  if (!body.cart_id || !body.delivery_option_id || !body.payment_gateway) {
    return json({ detail: "Missing checkout fields." }, 400);
  }
  if (isGuest) {
    if (!body.guest_email || !body.guest_phone || !body.address) {
      return json({ detail: "Missing guest checkout fields." }, 400);
    }
  } else if (!body.address_id) {
    return json({ detail: "Missing checkout fields." }, 400);
  }
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  // Prefer a client-supplied idempotency key: ReviewStep mints ONE key per checkout
  // attempt and reuses it across a Place-order retry, so a lost-201 (network blip
  // after the backend already created the order) resends the SAME key. The backend's
  // idempotency layer (begin()/finish() in idempotency.py) then replays the stored
  // 201 — bank details included — instead of hitting the now-converted cart and
  // returning a spurious cart_not_active. Fall back to minting one server-side for
  // any caller that doesn't send one. Never forward it in the upstream body — it's
  // a header concern only.
  const { idempotency_key: clientKey, referral_code: _ignored, ...upstreamBody } = body;
  const idempotencyKey = typeof clientKey === "string" && clientKey ? clientKey : randomUUID();
  // Referral attribution is read from the httpOnly cookie HERE and never from the
  // request body — a client-supplied `referral_code` is destructured out above and
  // discarded. The browser must not be able to name who gets paid: this is the only
  // field in the checkout payload that decides where money goes to a third party, and
  // the cookie can only have been set by the proxy having seen a real ?ref= navigation.
  //
  // Re-normalised rather than trusted: the cookie is ours, but a value that survived a
  // format change (or a hand-edited dev jar) should be dropped, not forwarded.
  const referralCode = normalizeReferralCode(jar.get(REFERRAL_COOKIE)?.value);
  try {
    const out = await fetchWithAuth<Record<string, unknown>>("/checkout/", {
      method: "POST", country,
      body: { ...upstreamBody, referral_code: referralCode },
      headers: { "Idempotency-Key": idempotencyKey },
    });
    // Guest 201: the token becomes an httpOnly cookie and leaves the payload (see
    // the route docstring). A same-key replay re-delivers it, so a guest whose
    // first response was lost to a network blip still ends up holding the cookie.
    if (isGuest && out && typeof out.guest_order_token === "string") {
      jar.set(GUEST_ORDER_COOKIE, out.guest_order_token,
              cookieOptions({ maxAge: GUEST_ORDER_MAX_AGE }));
      delete out.guest_order_token;
    }
    return json(out, 201);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
