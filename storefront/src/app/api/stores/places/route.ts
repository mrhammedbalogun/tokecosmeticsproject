import { cookies } from "next/headers";
import { apiFetch, ApiError } from "@/lib/api";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { selectionQuery } from "@/lib/stores";

/**
 * Public cascade proxy (Plan-42): `/api/stores/places?country=…&state=…` →
 * `apps.stores.views.StorePlacesView`. Same shape and reason as `/api/regions` — the
 * browser cannot call Django (API_URL is server-only), so every client-side step of
 * the locator's cascade comes through here.
 *
 * ANONYMOUS. No Authorization header is forwarded and none is wanted: the upstream
 * view sets `authentication_classes = []`, and a locator that behaved differently for
 * a signed-in reader would be a bug.
 *
 * The market cookie rides along as X-Country so the store cards' phone numbers are
 * formatted for the reader (national form at home, international abroad).
 */
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const qs = selectionQuery({
    country: url.searchParams.get("country"),
    state: url.searchParams.get("state"),
  });
  const market = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  try {
    const data = await apiFetch(`/stores/places/${qs ? `?${qs}` : ""}`, {
      country: market,
      cache: "no-store",
    });
    return json(data);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 502);
  }
}
