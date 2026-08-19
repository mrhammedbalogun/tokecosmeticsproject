import { cookies } from "next/headers";
import { ApiError, apiFetch } from "@/lib/api";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

/** Guest GIG centre-picker proxy (Plan-38) — mirrors guest-delivery-options:
 * anonymous, POST-only (inline address is PII), non-empty guest cart required
 * upstream. Plain apiFetch — there is no session to refresh. */
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
    return json(await apiFetch("/checkout/guest/gig-centres/", {
      method: "POST", country, body, cache: "no-store",
    }));
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
