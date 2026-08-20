/**
 * The delivery-partner portal's BFF proxy (Plan-39) — `/api/partner/a/b` → Django
 * `/partner/a/b/`, with the PARTNER cookie pair attached server-side.
 *
 * A separate handler rather than a branch in the generic `/api/[...path]` proxy, on
 * purpose: that proxy is defined to attach `admin_access` and only `admin_access`,
 * and the whole lesson of its docstring is that credential-picking helpers are where
 * "the wrong token went upstream" bugs are born. This one attaches `partner_access`
 * and only `partner_access` (via `partnerFetchRaw`), and its upstream is PINNED to
 * the `/partner/` prefix by construction — it cannot be asked to reach an admin or
 * customer endpoint no matter what path the browser sends. Next's router prefers this
 * route's static `partner` segment over the root catch-all, so partner traffic can
 * never fall through to the admin proxy either.
 *
 * CSRF: same story as the generic proxy — SameSite=Strict on both partner cookies
 * means a cross-site fetch arrives credential-less and Django refuses it.
 *
 * JSON only: the portal is one rate table; it uploads nothing.
 */
import { partnerFetchRaw } from "@/lib/partner-session";

const NO_STORE = {
  "content-type": "application/json",
  "cache-control": "no-store, no-cache, must-revalidate, private",
};

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: NO_STORE });
}

function upstreamPath(rawSegments: string[], search: string): string | null {
  const segments = rawSegments.filter((s) => s !== "");
  if (!segments.length) return null;
  if (segments.some((s) => s === "." || s === ".." || s.includes("/") || s.includes("\\"))) {
    return null;
  }
  return `/partner/${segments.map(encodeURIComponent).join("/")}/${search}`;
}

async function handle(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = await ctx.params;
  const url = new URL(req.url);
  const target = upstreamPath(path, url.search);
  if (!target) return json({ detail: "Bad request." }, 400);

  let body: Record<string, unknown> | undefined;
  if (!(req.method === "GET" || req.method === "DELETE" || req.method === "HEAD")) {
    const raw = await req.text();
    if (!raw) {
      body = {};
    } else {
      try {
        body = JSON.parse(raw);
      } catch {
        return json({ detail: "Request body is not valid JSON." }, 400);
      }
    }
  }

  let res: Response;
  try {
    res = await partnerFetchRaw(target, { method: req.method, body });
  } catch {
    return json({ detail: "The API is not responding." }, 502);
  }

  const text = await res.text();
  return new Response(text || null, { status: res.status, headers: NO_STORE });
}

export {
  handle as GET,
  handle as POST,
  handle as PATCH,
  handle as PUT,
  handle as DELETE,
};
