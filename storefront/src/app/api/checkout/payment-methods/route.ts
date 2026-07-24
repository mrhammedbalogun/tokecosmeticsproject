import { cookies } from "next/headers";
import { apiFetch, ApiError } from "@/lib/api";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

/** Public payment-methods proxy (Plan-14 Task 9): PaymentStep's step-4 chooser reads
 * the active gateways for the shopper's country. Public (AllowAny) data, same shape
 * as regions/route.ts — no auth forwarded, ?country=<CC> falls back to the country
 * cookie / DEFAULT_COUNTRY when the caller doesn't pass one. */
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const jar = await cookies();
  const country = url.searchParams.get("country") ?? jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  try {
    const data = await apiFetch(`/checkout/payment-methods/?country=${encodeURIComponent(country)}`, {
      country, cache: "no-store",
    });
    return json(data);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
