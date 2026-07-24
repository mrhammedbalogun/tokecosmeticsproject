import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

/** Address-book proxy (Plan-14 Task 7): list + create under the authed customer's
 * /me/addresses/. Mirrors the buy-now/route.ts guard + ApiError passthrough
 * pattern — the browser never sees the access token, fetchWithAuth reads it from
 * httpOnly cookies server-side. */
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

async function hasSession(): Promise<boolean> {
  const jar = await cookies();
  return Boolean(jar.get(ACCESS_COOKIE)?.value || jar.get(REFRESH_COOKIE)?.value);
}

export async function GET() {
  if (!(await hasSession())) return json({ detail: "Not authenticated." }, 401);
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  try {
    return json(await fetchWithAuth("/me/addresses/", { country }));
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}

export async function POST(req: Request) {
  if (!(await hasSession())) return json({ detail: "Not authenticated." }, 401);
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const body = await req.json().catch(() => ({}));
  try {
    return json(await fetchWithAuth("/me/addresses/", { method: "POST", country, body }), 201);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
