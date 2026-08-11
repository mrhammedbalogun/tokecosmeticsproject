import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

/** GIG centre-picker proxy (Plan-32b slice 4). Authed; proxies the read-only
 * nearest-centres list for an address so DeliveryStep's pickup option can render
 * the picker. Mirrors delivery-options/route.ts. */
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
  const addressId = new URL(req.url).searchParams.get("address_id");
  if (!addressId) {
    return json({ detail: "Provide address_id." }, 400);
  }
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  try {
    return json(await fetchWithAuth(
      `/checkout/gig-centres/?address_id=${encodeURIComponent(addressId)}`,
      { country, cache: "no-store" },
    ));
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
