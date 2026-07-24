import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

/** Delivery-options proxy (Plan-14 Task 8). Authed; proxies the read-only delivery
 * quote list for a given (address, cart) pair so DeliveryStep can render selectable
 * options without exposing the Django host to the browser. */
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

export async function GET(req: Request) {
  const jar = await cookies();
  if (!jar.get(ACCESS_COOKIE)?.value && !jar.get(REFRESH_COOKIE)?.value) {
    return json({ detail: "Not authenticated." }, 401);
  }
  const url = new URL(req.url);
  const addressId = url.searchParams.get("address_id");
  const cartId = url.searchParams.get("cart_id");
  if (!addressId || !cartId) {
    return json({ detail: "Provide address_id and cart_id." }, 400);
  }
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const qs = `address_id=${encodeURIComponent(addressId)}&cart_id=${encodeURIComponent(cartId)}`;
  try {
    return json(await fetchWithAuth(`/checkout/delivery-options/?${qs}`, { country, cache: "no-store" }));
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
