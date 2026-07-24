import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

/** Buy-Now proxy (Plan-13 D6). Authed-only by backend design: creates/refills the
 * user's express cart with exactly this item. Guests never reach here — the client
 * stashes intent and routes to /login. NOT a checkout placement — Plan-14 owns that. */
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

export async function POST(req: Request) {
  const jar = await cookies();
  if (!jar.get(ACCESS_COOKIE)?.value && !jar.get(REFRESH_COOKIE)?.value) {
    return json({ detail: "Not authenticated." }, 401);
  }
  const body = await req.json().catch(() => ({}));
  if (!body.variant_id) return json({ variant_id: ["This field is required."] }, 400);
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  try {
    const cart = await fetchWithAuth("/checkout/buy-now/", {
      method: "POST", country,
      body: { variant_id: body.variant_id, quantity: body.quantity ?? 1 },
    });
    return json(cart);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
