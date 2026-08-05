import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";

/** Authed "may I review this product?" probe for the PDP review form. A Route
 * Handler (not a Server-Component fetch) on purpose: the access cookie lives 14
 * minutes, so the probe must be allowed to silently refresh — which only a Route
 * Handler may do (see lib/session.ts). The browser never sees the token. */
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function hasSession(): Promise<boolean> {
  const jar = await cookies();
  return Boolean(jar.get(ACCESS_COOKIE)?.value || jar.get(REFRESH_COOKIE)?.value);
}

export async function GET(_req: Request, ctx: { params: Promise<{ slug: string }> }) {
  if (!(await hasSession())) return json({ detail: "Not authenticated." }, 401);
  const { slug } = await ctx.params;
  try {
    return json(
      await fetchWithAuth(`/products/${encodeURIComponent(slug)}/reviews/eligibility/`),
    );
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
