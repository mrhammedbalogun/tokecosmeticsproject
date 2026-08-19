import { cookies } from "next/headers";
import { ApiError, apiFetch } from "@/lib/api";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

/** Guest delivery-options proxy (Plan-38). Anonymous by design: the guest twin of
 * delivery-options takes the INLINE address in a POST body (PII stays out of URL
 * logs) plus the guest cart id, and the backend refuses anything but a non-empty
 * guest cart. Plain apiFetch — there is no session to refresh. Doubles as the guest
 * address form's validation pass: DRF field errors come back under `address`. */
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

export async function POST(req: Request) {
  const jar = await cookies();
  const body = await req.json().catch(() => ({}));
  if (!body.cart_id || !body.address) {
    return json({ detail: "Provide cart_id and address." }, 400);
  }
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  try {
    return json(await apiFetch("/checkout/guest/delivery-options/", {
      method: "POST", country, body, cache: "no-store",
    }));
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
