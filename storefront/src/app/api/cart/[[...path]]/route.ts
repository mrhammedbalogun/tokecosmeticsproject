import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { CART_COOKIE, CART_MAX_AGE, cookieOptions } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

interface Cart { id: string; [k: string]: unknown }

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
}

async function proxy(method: string, segments: string[], body: unknown | undefined) {
  const jar = await cookies();
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const cartId = jar.get(CART_COOKIE)?.value;

  // Map /api/cart[/items[/:variantId]] -> Django /cart/[items/[:variantId/]]
  const path = segments.length ? `/cart/${segments.join("/")}/` : "/cart/";
  // fetchWithAuth, NOT a raw ACCESS_COOKIE read: the access cookie lives 14 min, and a
  // signed-in shopper whose token lapsed mid-browse would otherwise hit the backend
  // anonymously — which can't match their user-owned cart, mints a fresh guest cart,
  // and reads as "my cart emptied itself". The silent refresh keeps cart requests
  // authenticated for the whole 14-day refresh window. (Anonymous guests still work:
  // no token, no refresh, cart endpoints are AllowAny.)
  const cart = await fetchWithAuth<Cart>(path, { method, body, country, cartId });

  // Persist the authoritative guest cart id (backend creates one on first call).
  // For an authed user the cart is server-owned; we still cache the id harmlessly.
  // Max-age, not session-scoped: a guest's cart must survive closing the browser.
  if (cart?.id && cart.id !== cartId) {
    jar.set(CART_COOKIE, cart.id, cookieOptions({ maxAge: CART_MAX_AGE }));
  }
  return json(cart);
}

async function handle(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = await ctx.params;
  const body = req.method === "GET" || req.method === "DELETE"
    ? undefined
    : await req.json().catch(() => ({}));
  try {
    return await proxy(req.method, path, body);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Cart error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const DELETE = handle;
