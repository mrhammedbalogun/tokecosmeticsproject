import { cookies } from "next/headers";
import { apiFetch, ApiError } from "@/lib/api";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

/** Debounced-autocomplete proxy. Forwards the caller's IP so the backend's
 * 60/min/IP suggest throttle stays per-user (prod proxy-trust note: Plan-02/22). */
export async function GET(req: Request) {
  const url = new URL(req.url);
  const q = (url.searchParams.get("q") ?? "").trim();
  const json = (data: unknown, status = 200) =>
    new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
  if (!q) return json([]);
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const ip = req.headers.get("x-forwarded-for") ?? "";
  try {
    const data = await apiFetch(`/search/suggest/?q=${encodeURIComponent(q)}`, {
      country, cache: "no-store",
      headers: ip ? { "X-Forwarded-For": ip } : {},
    });
    return json(data);
  } catch (e) {
    if (e instanceof ApiError && e.status === 429) return json([]); // throttled -> quiet
    return json([], 200); // suggestions are best-effort; never surface errors
  }
}
