import { cookies } from "next/headers";
import { randomUUID } from "node:crypto";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

/** Place order (Plan-14). Authed; generates the Idempotency-Key server-side so a
 * double-click can't double-charge. Bank-transfer details ride back in payment.data. */
export async function POST(req: Request) {
  const jar = await cookies();
  if (!jar.get(ACCESS_COOKIE)?.value && !jar.get(REFRESH_COOKIE)?.value) {
    return json({ detail: "Not authenticated." }, 401);
  }
  const body = await req.json().catch(() => ({}));
  if (!body.cart_id || !body.address_id || !body.delivery_option_id || !body.payment_gateway) {
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
  const { idempotency_key: clientKey, ...upstreamBody } = body;
  const idempotencyKey = typeof clientKey === "string" && clientKey ? clientKey : randomUUID();
  try {
    const out = await fetchWithAuth("/checkout/", {
      method: "POST", country, body: upstreamBody,
      headers: { "Idempotency-Key": idempotencyKey },
    });
    return json(out, 201);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
