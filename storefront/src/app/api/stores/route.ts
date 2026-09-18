import { cookies } from "next/headers";
import { apiFetch, ApiError } from "@/lib/api";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { selectionQuery } from "@/lib/stores";

/**
 * Public store-results proxy (Plan-42): `/api/stores?country=…&state=…&area=…` →
 * `apps.stores.views.StoreListView`. See `places/route.ts` for why the proxy exists
 * at all and why nothing authenticates.
 *
 * `page` is forwarded because the upstream list is PAGINATED rather than capped — the
 * "Show more" control on the results panel is what pages it, and dropping the param
 * here would make that button reload page one forever.
 *
 * ── NO `Cache-Control: public` HERE. THE BODY VARIES BY A COOKIE. ───────────────────
 *
 * The market cookie goes upstream as X-Country and the serializer formats every phone
 * number against it (`apps/core/phones.py::format_display`: national at home,
 * international abroad). Measured 2026-09-14 on the same URL:
 *
 *     X-Country: NG  ->  "0707 480 0702"
 *     X-Country: GB  ->  "+234 707 480 0702"
 *
 * A shared cache keys on the URL, not on cookies, so a public header here would let one
 * visitor's market leak into another's response — a UK reader shown a local Nigerian
 * number they cannot dial. `Vary: Cookie` would be correct and useless (every distinct
 * cookie string is its own entry, and these visitors all carry cart/consent cookies).
 *
 * The DATA cache is safe and is where the win is: Next hashes request headers into the
 * fetch cache key (`incremental-cache/index.js` — url, method, bodyType, headers, …), so
 * X-Country NG and GB are separate entries and Django stops being asked per request.
 * Making the response publicly cacheable would mean moving the market into the URL,
 * which changes the client contract — a bigger decision than this task.
 */
const STORES_REVALIDATE = 300;
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const country = url.searchParams.get("country");
  if (!country) return json({ detail: "Choose a country first." }, 400);

  const params = new URLSearchParams(
    selectionQuery({
      country,
      state: url.searchParams.get("state"),
      area: url.searchParams.get("area"),
    }),
  );
  const page = url.searchParams.get("page");
  // Numeric only — the value lands in an upstream query string, and a page number is
  // the one thing this route knows the shape of.
  if (page && /^\d+$/.test(page)) params.set("page", page);

  const market = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  try {
    // Same 300s + "stores" tag as `lib/stores.ts:119`; `apps/stores/revalidate.py`
    // flushes that tag on any store write, so an edit is visible at once.
    const data = await apiFetch(`/stores/?${params.toString()}`, {
      country: market,
      next: { revalidate: STORES_REVALIDATE, tags: ["stores"] },
    });
    return json(data);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 502);
  }
}
