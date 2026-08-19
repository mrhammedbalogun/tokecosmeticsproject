import { cookies } from "next/headers";
import { randomUUID } from "node:crypto";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, GUEST_ORDER_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

/** Re-open payment on an order that is still awaiting it, optionally on a different
 * gateway (Plan-14b; guests since Plan-38). Authed callers are scoped by the backend
 * to their own orders (404 otherwise). A guest holds the httpOnly guest-order cookie
 * set at placement — its signed token is forwarded in the body and stands in for
 * auth, scoped to the one order it names. Either way a guessed order number reaches
 * nobody else's order.
 *
 * The key is minted here when the caller doesn't supply one, for the same reason as
 * place-order: a lost response must resume the SAME attempt rather than opening a
 * second one at the gateway. It is a header concern and never forwarded in the body. */
export async function POST(req: Request) {
  const jar = await cookies();
  const authed = Boolean(jar.get(ACCESS_COOKIE)?.value || jar.get(REFRESH_COOKIE)?.value);
  const guestToken = jar.get(GUEST_ORDER_COOKIE)?.value;
  if (!authed && !guestToken) {
    return json({ detail: "Not authenticated." }, 401);
  }
  const body = await req.json().catch(() => ({}));
  const orderNumber = typeof body.order_number === "string" ? body.order_number : "";
  const gateway = typeof body.payment_gateway === "string" ? body.payment_gateway : "";
  if (!orderNumber || !gateway) return json({ detail: "Missing order or payment method." }, 400);

  const clientKey = body.idempotency_key;
  const idempotencyKey = typeof clientKey === "string" && clientKey ? clientKey : randomUUID();
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  try {
    const out = await fetchWithAuth(`/orders/${encodeURIComponent(orderNumber)}/pay/`, {
      method: "POST",
      country,
      // An authed session wins over a stale guest cookie — same rule as verify.
      body: authed
        ? { payment_gateway: gateway }
        : { payment_gateway: gateway, guest_token: guestToken },
      headers: { "Idempotency-Key": idempotencyKey },
    });
    return json(out, 200);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
