import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

/** Set-default proxy (Plan-15d Task 1): POST { kind: "shipping" | "billing" } →
 * upstream /me/addresses/{id}/set-default-{kind}/. `is_default_shipping` and
 * `is_default_billing` are read-only on the upstream serializer — this is the only
 * route that changes them. Mirrors ../route.ts's guard + ApiError passthrough. */
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

async function hasSession(): Promise<boolean> {
  const jar = await cookies();
  return Boolean(jar.get(ACCESS_COOKIE)?.value || jar.get(REFRESH_COOKIE)?.value);
}

const ADDRESS_ID = /^\d{1,10}$/;
const notFound = () => json({ detail: "Not found." }, 404);

// Fixed allowlist: the upstream path segment is interpolated ONLY from one of these
// two literals, never from the request body's `kind` value directly.
const KIND_PATH: Record<string, string> = {
  shipping: "set-default-shipping",
  billing: "set-default-billing",
};

export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!(await hasSession())) return json({ detail: "Not authenticated." }, 401);
  const { id } = await ctx.params;
  if (!ADDRESS_ID.test(id)) return notFound();

  const body = await req.json().catch(() => ({}));
  const kind = (body as { kind?: unknown }).kind;
  const action = typeof kind === "string" ? KIND_PATH[kind] : undefined;
  if (!action) return json({ detail: "Invalid kind." }, 400);

  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  try {
    return json(
      await fetchWithAuth(`/me/addresses/${id}/${action}/`, { method: "POST", country }),
    );
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
