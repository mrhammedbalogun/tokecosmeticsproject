import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

/** Quote proxy (Plan-14 Task 3; guests since Plan-38). Proxies the read-only totals
 * endpoint so the cart/checkout UI can preview totals + validate a coupon before
 * placing the order. Never mutates anything server-side. A guest request (no session
 * cookies) is routed to the guest twin, which takes the inline address + guest_email
 * instead of a saved address id. */
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

export async function POST(req: Request) {
  const jar = await cookies();
  const isGuest = !jar.get(ACCESS_COOKIE)?.value && !jar.get(REFRESH_COOKIE)?.value;
  const body = await req.json().catch(() => ({}));
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const path = isGuest ? "/checkout/guest/quote/" : "/checkout/quote/";
  try {
    return json(await fetchWithAuth(path, { method: "POST", country, body }));
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
