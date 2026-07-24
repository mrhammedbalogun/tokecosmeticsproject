import { apiFetch, ApiError } from "@/lib/api";

/** Public region-browser proxy (Plan-14 Task 7): the address form's State/LGA
 * dropdowns drive off apps.delivery.views.RegionBrowseView. NOTE: despite the
 * app being named "delivery", its urls.py is included under the "meta/" prefix
 * in config/urls.py, so the real upstream path is /api/v1/meta/regions/ — not
 * /api/v1/regions/. Public (AllowAny) data — no auth forwarded. Forwards either
 * ?country=<CC> (top-level states) or ?parent=<id> (children) from the request. */
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
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
    const data = await apiFetch(`/meta/regions/?${qs}`, { cache: "no-store" });
    return json(data);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
