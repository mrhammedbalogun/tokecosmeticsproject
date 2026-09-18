import { apiFetch, ApiError } from "@/lib/api";

/** Public region-browser proxy (Plan-14 Task 7): the address form's State/LGA
 * dropdowns drive off apps.delivery.views.RegionBrowseView. NOTE: despite the
 * app being named "delivery", its urls.py is included under the "meta/" prefix
 * in config/urls.py, so the real upstream path is /api/v1/meta/regions/ — not
 * /api/v1/regions/. Public (AllowAny) data — no auth forwarded. Forwards either
 * ?country=<CC> (top-level states) or ?parent=<id> (children) from the request. */

/** A day. This is administrative geography — Nigeria's 37 states and their LGAs, the
 * four UK nations, the 51 US entries — which changes when a government redraws a
 * boundary, not when a shopper opens the address form. It was `no-store`, so every
 * mount of every address form on every checkout and account page went all the way to
 * Django for a 3.5KB table that had not moved in months. */
const REGIONS_REVALIDATE = 86400;

/** `s-maxage` only, deliberately: the shared caches (Vercel's edge, any CDN in front)
 * hold it for a day, while a browser keeps nothing of its own. The dropdown is filled
 * from a fetch the page makes anyway, so per-browser caching buys little, and leaving
 * `max-age` at the default keeps a corrected region list one edge purge away from every
 * visitor rather than stranded in caches we cannot reach. */
const REGIONS_CACHE_CONTROL = "public, s-maxage=86400, stale-while-revalidate=86400";

function json(data: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json", ...headers },
  });
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const country = url.searchParams.get("country");
  const parent = url.searchParams.get("parent");
  if (!country && !parent) {
    return json({ detail: "Provide ?country=<CC> or ?parent=<id>." }, 400);
  }
  const qs = country
    ? `country=${encodeURIComponent(country)}`
    : `parent=${encodeURIComponent(parent as string)}`;
  try {
    // The cache key is the UPSTREAM URL, and `qs` is in it — so `?country=NG` (37
    // states), `?country=GB` (4 nations) and `?parent=12` (that state's LGAs) are three
    // separate entries and can never be served for one another. Nothing else varies the
    // response: this route reads no cookie and no request header, and `apiFetch` sends a
    // constant X-Country here because no `country` option is passed to it.
    //
    // The `regions` tag exists so `POST /api/revalidate` can flush this the moment a
    // region IS added, which is what makes a 24-hour TTL safe rather than merely cheap.
    const data = await apiFetch(`/meta/regions/?${qs}`, {
      next: { revalidate: REGIONS_REVALIDATE, tags: ["regions"] },
    });
    return json(data, 200, { "cache-control": REGIONS_CACHE_CONTROL });
  } catch (e) {
    // Error responses carry NO Cache-Control, on purpose. The Django origin sits behind
    // Cloudflare and intermittently answers 522 (measured ~8% on this route), and a 522
    // cached for a day would empty the State dropdown for everyone until it expired.
    // Next's data cache agrees independently — `patch-fetch` only writes on a 200 — so a
    // failure is never stored at either layer and the next request retries.
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
