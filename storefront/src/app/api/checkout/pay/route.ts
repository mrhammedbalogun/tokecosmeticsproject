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

/** Re-open payment on an order that is still awaiting it, optionally on a different
 * gateway (Plan-14b). Authed; the backend scopes the order to the requesting user and
 * 404s otherwise, so a guessed order number can't reach anyone else's order.
 *
 * The key is minted here when the caller doesn't supply one, for the same reason as
 * place-order: a lost response must resume the SAME attempt rather than opening a
 * second one at the gateway. It is a header concern and never forwarded in the body. */
export async function POST(req: Request) {
  const jar = await cookies();
  if (!jar.get(ACCESS_COOKIE)?.value && !jar.get(REFRESH_COOKIE)?.value) {
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
      body: { payment_gateway: gateway },
      headers: { "Idempotency-Key": idempotencyKey },
    });
    return json(out, 200);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
