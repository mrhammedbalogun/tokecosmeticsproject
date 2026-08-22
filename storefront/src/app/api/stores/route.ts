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
 */
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
    const data = await apiFetch(`/stores/?${params.toString()}`, {
      country: market,
      cache: "no-store",
    });
    return json(data);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 502);
  }
}
