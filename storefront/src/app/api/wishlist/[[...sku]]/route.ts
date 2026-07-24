import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";

/** Authed wishlist proxy (backend is sku-keyed under /me/wishlist/). The browser
 * never sees the token — fetchWithAuth reads httpOnly cookies server-side. */
function json(data: unknown, status = 200) {
  return new Response(data === null ? null : JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function hasSession(): Promise<boolean> {
  const jar = await cookies();
  return Boolean(jar.get(ACCESS_COOKIE)?.value || jar.get(REFRESH_COOKIE)?.value);
}

function onError(e: unknown) {
  if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
  return json({ detail: "Unexpected error." }, 500);
}

export async function GET(_req: Request, _ctx: { params: Promise<{ sku?: string[] }> }) {
  if (!(await hasSession())) return json({ detail: "Not authenticated." }, 401);
  try {
    return json(await fetchWithAuth("/me/wishlist/"));
  } catch (e) {
    return onError(e);
  }
}

export async function POST(req: Request, _ctx: { params: Promise<{ sku?: string[] }> }) {
  if (!(await hasSession())) return json({ detail: "Not authenticated." }, 401);
  const body = await req.json().catch(() => ({}));
  try {
    return json(await fetchWithAuth("/me/wishlist/", { method: "POST", body }), 201);
  } catch (e) {
    return onError(e);
  }
}

export async function DELETE(_req: Request, ctx: { params: Promise<{ sku?: string[] }> }) {
  if (!(await hasSession())) return json({ detail: "Not authenticated." }, 401);
  const { sku } = await ctx.params;
  if (!sku?.[0]) return json({ detail: "sku required." }, 400);
  try {
    await fetchWithAuth(`/me/wishlist/${encodeURIComponent(sku[0])}/`, { method: "DELETE" });
    return new Response(null, { status: 204 });
  } catch (e) {
    return onError(e);
  }
}
