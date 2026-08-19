import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, GUEST_ORDER_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

/** Re-verify a payment on customer return / inline callback (Plan-14b; guests since
 * Plan-38). Authed callers are scoped by the backend to their own orders. A guest
 * has no session but holds the httpOnly guest-order cookie set at placement — its
 * signed token is forwarded in the body and scopes the lookup to the one order it
 * names. Either way a guessed reference can't leak another shopper's order.
 *
 * The cookie path is what survives Paystack's dashboard-callback fallback, which
 * strips our return-URL query string — the reference arrives bare, and the cookie
 * is the only guest credential left standing. */
export async function POST(req: Request) {
  const jar = await cookies();
  const authed = Boolean(jar.get(ACCESS_COOKIE)?.value || jar.get(REFRESH_COOKIE)?.value);
  const guestToken = jar.get(GUEST_ORDER_COOKIE)?.value;
  if (!authed && !guestToken) {
    return json({ detail: "Not authenticated." }, 401);
  }
  const body = await req.json().catch(() => ({}));
  const reference = typeof body.reference === "string" ? body.reference : "";
  if (!reference) return json({ detail: "Missing reference." }, 400);
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  try {
    const out = await fetchWithAuth(
      `/payments/${encodeURIComponent(reference)}/verify/`,
      { method: "POST", country, body: authed ? {} : { guest_token: guestToken } },
    );
    return json(out, 200);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
