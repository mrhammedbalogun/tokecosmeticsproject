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
 *
 * ── WHY THIS ONE MAY GO IN A SHARED CACHE AND `../route.ts` MAY NOT ─────────────────
 *
 * This endpoint returns the CASCADE — country / state / area names and store counts. It
 * carries no phone numbers, so the X-Country above changes nothing in its body. Measured
 * 2026-09-14 against the live API: `/stores/places/?country=NG` is byte-identical under
 * X-Country NG, GB, US and ZZ (same md5). The sibling `/api/stores` is NOT — its phone
 * fields differ per market — so it deliberately stops at the data cache. Do not copy the
 * header below into it.
 */
const STORES_REVALIDATE = 300;
/** Matches `lib/stores.ts`, which serves the same data server-side. */
const PLACES_CACHE_CONTROL = "public, s-maxage=300, stale-while-revalidate=300";

function json(data: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json", ...headers },
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
    // `revalidate` + the `stores` tag, exactly as `lib/stores.ts:151` does for the
    // server-rendered half — and the tag is live: `apps/stores/revalidate.py` flushes
    // "stores" on any store write, so an edit lands immediately rather than after 300s.
    const data = await apiFetch(`/stores/places/${qs ? `?${qs}` : ""}`, {
      country: market,
      next: { revalidate: STORES_REVALIDATE, tags: ["stores"] },
    });
    return json(data, 200, { "cache-control": PLACES_CACHE_CONTROL });
  } catch (e) {
    // No Cache-Control on a failure: the Django origin sits behind Cloudflare and
    // intermittently answers 522, and a cached 5-minute outage would empty the locator's
    // dropdowns for everyone. Next's data cache agrees independently — `patch-fetch`
    // only writes on a 200.
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 502);
  }
}
