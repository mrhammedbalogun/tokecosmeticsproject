import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

/** Address-book proxy (Plan-15d Task 1): update/delete a single address under the
 * authed customer's /me/addresses/{id}/. Mirrors ../route.ts's hasSession() guard,
 * fetchWithAuth call, and ApiError passthrough pattern. */
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

async function hasSession(): Promise<boolean> {
  const jar = await cookies();
  return Boolean(jar.get(ACCESS_COOKIE)?.value || jar.get(REFRESH_COOKIE)?.value);
}

// Owner-scoped upstream ids are numeric primary keys. Anything outside this shape
// cannot name a real address, so it is rejected before the network is asked.
const ADDRESS_ID = /^\d{1,10}$/;

const notFound = () => json({ detail: "Not found." }, 404);

export async function PATCH(req: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!(await hasSession())) return json({ detail: "Not authenticated." }, 401);
  // Next hands `id` back decoded; params is a Promise.
  const { id } = await ctx.params;
  if (!ADDRESS_ID.test(id)) return notFound();
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const body = await req.json().catch(() => ({}));
  try {
    return json(
      await fetchWithAuth(`/me/addresses/${id}/`, { method: "PATCH", country, body }),
    );
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}

export async function DELETE(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!(await hasSession())) return json({ detail: "Not authenticated." }, 401);
  const { id } = await ctx.params;
  if (!ADDRESS_ID.test(id)) return notFound();
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  try {
    await fetchWithAuth(`/me/addresses/${id}/`, { method: "DELETE", country });
    return new Response(null, { status: 204 });
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
