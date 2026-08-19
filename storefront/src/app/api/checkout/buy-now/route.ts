import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { CART_COOKIE, CART_MAX_AGE, cookieOptions } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

/** Buy-Now proxy (Plan-13 D6; guests since Plan-38). Adds this item to the shopper's
 * STANDARD cart — the same cart checkout reads. (Express carts retired 2026-07-28:
 * nothing ever consumed them, so Buy Now reached checkout with an empty cart.)
 * Guests work exactly like the cart proxy: the cart cookie rides up as X-Cart-Id and
 * whatever id the backend answers with is persisted, so a first-ever Buy Now mints
 * the guest cart AND keeps it. NOT a checkout placement — Plan-14 owns that. */
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

interface Cart { id: string; [k: string]: unknown }

export async function POST(req: Request) {
  const jar = await cookies();
  const body = await req.json().catch(() => ({}));
  if (!body.variant_id) return json({ variant_id: ["This field is required."] }, 400);
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const cartId = jar.get(CART_COOKIE)?.value;
  try {
    const cart = await fetchWithAuth<Cart>("/checkout/buy-now/", {
      method: "POST", country, cartId,
      body: { variant_id: body.variant_id, quantity: body.quantity ?? 1 },
    });
    // Same persistence rule as the cart proxy: the backend's answer is authoritative
    // (it mints a guest cart on first call), and a guest's cart must survive the tab.
    if (cart?.id && cart.id !== cartId) {
      jar.set(CART_COOKIE, cart.id, cookieOptions({ maxAge: CART_MAX_AGE }));
    }
    return json(cart);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
