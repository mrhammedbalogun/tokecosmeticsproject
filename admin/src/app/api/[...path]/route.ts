/**
 * The generic authenticated proxy — the one BFF route the whole admin UI fetches through.
 *
 * It exists so the browser never holds a JWT: cookies stay httpOnly, this handler attaches
 * the Bearer header server-side, and a rotated pair can be persisted because a Route
 * Handler may write cookies.
 *
 * ── IT READS `admin_access`, AND ONLY `admin_access` ───────────────────────────────
 *
 * This is the single most important line in the file, and it is a direct descendant of the
 * bug that nearly shipped in Task 3b: a class that DECLARED it checked a claim and then
 * did not. The temptation here is a "helpful" helper that grabs whichever token cookie is
 * present, which would forward a PREAUTH token — a credential defined to open exactly
 * three TOTP endpoints — to whatever the caller asked for.
 *
 * It would not be a privilege escalation (the backend refuses it: `CustomerJWTAuthentication`
 * is the project default and rejects preauth tokens, and `AdminJWTAuthentication` accepts
 * only the completed-ceremony audience). It would be a credential doing something its own
 * definition forbids, which is how the concept of "half-authenticated" stops meaning
 * anything. `decideAuth(..., "bff", ...)` answers `unauthenticated` for a preauth-only
 * request and this handler returns 401 WITHOUT calling upstream at all — asserted in
 * `__tests__/route.test.ts`.
 *
 * ── CSRF ───────────────────────────────────────────────────────────────────────────
 *
 * Server Functions get Next's Origin/Host check for free; a JSON Route Handler does not.
 * What protects this one is `SameSite=Strict` on every admin cookie (`lib/auth.ts`): a
 * cross-site fetch carries no credential, so it reaches Django as an anonymous request and
 * is refused there. That is why the Strict-over-Lax choice is not cosmetic.
 */
import { cookies } from "next/headers";
import { ApiError, apiFetchRaw, drainBody } from "@/lib/api";
import { ACCESS_COOKIE, PREAUTH_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { decideAuth } from "@/lib/auth-guard";
import { clearSession } from "@/lib/admin-session";
import { refreshAndPersist } from "@/lib/session";

const NO_STORE = {
  "content-type": "application/json",
  // Belt and braces with `proxy.ts`: a BFF response is the one thing in this app that
  // MUST never be cached, and it should not depend on a matcher staying correct.
  "cache-control": "no-store, no-cache, must-revalidate, private",
};

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: NO_STORE });
}

/** A final segment that names a file — `export.csv`, `invoice.pdf`. See `upstreamPath`. */
const FILENAME_SEGMENT = /\.[a-z0-9]{2,4}$/i;

/**
 * `/api/a/b/` -> Django `/a/b/`. Rejects traversal segments outright rather than trusting
 * URL normalisation to have already removed them: this string is concatenated into a URL
 * that carries an administrator's bearer token.
 *
 * ── THE TRAILING SLASH IS NOT UNCONDITIONAL ────────────────────────────────────────
 *
 * It used to be, on the stated ground that "Django's URLconf ends every endpoint in a
 * slash". That stopped being true the moment Plan-18a added the two download routes, which
 * are registered WITHOUT one (`orders/export.csv`, `orders/<number>/invoice.pdf`) so that
 * `orders/<str:number>/` cannot swallow them. Appending a slash to those turned
 * `orders/export.csv` into `orders/export.csv/`, which then matched
 * `orders/<str:number>/` with `number="export.csv"` — so the export button and the invoice
 * link both answered 404 "No Order matches the given query", the exact failure the
 * URLconf's own comment set out to prevent. Every unit test passed throughout: they mock
 * `fetch`, so none of them traverses this function.
 *
 * So: a final segment that names a file is sent as-is, everything else keeps its slash.
 */
function upstreamPath(rawSegments: string[], search: string): string | null {
  // Next redirects `/api/x/` to `/api/x` (308, method and body preserved) before this
  // handler runs, so callers should use no trailing slash. The filter is belt and braces.
  const segments = rawSegments.filter((s) => s !== "");
  if (!segments.length) return null;
  if (segments.some((s) => s === "." || s === ".." || s.includes("/") || s.includes("\\"))) {
    return null;
  }
  const path = segments.map(encodeURIComponent).join("/");
  const slash = FILENAME_SEGMENT.test(segments[segments.length - 1]) ? "" : "/";
  return `/${path}${slash}${search}`;
}

async function handle(req: Request, ctx: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = await ctx.params;
  const url = new URL(req.url);
  const target = upstreamPath(path, url.search);
  if (!target) return json({ detail: "Bad request." }, 400);

  const jar = await cookies();
  const decision = decideAuth(
    {
      access: jar.get(ACCESS_COOKIE)?.value,
      refresh: jar.get(REFRESH_COOKIE)?.value,
      preauth: jar.get(PREAUTH_COOKIE)?.value,
    },
    "bff",
    url.pathname,
  );

  if (decision.kind === "purge") {
    clearSession(jar);
    return json({ detail: "Session invalid. Sign in again." }, 401);
  }
  // No usable session. Nothing is sent upstream — in particular, no preauth token.
  if (decision.kind === "unauthenticated") {
    return json({ detail: "Not authenticated." }, 401);
  }

  // MULTIPART IS READ AS MULTIPART. `req.json()` on a file upload does not merely fail —
  // it fails into `{}` via the catch below, so the request reached Django as an empty JSON
  // body and the FILE WAS SILENTLY DISCARDED. Django answered 415, which reads like a
  // client mistake rather than the proxy having thrown the payload away. Every upload the
  // admin will ever do goes through here: the stock CSV import and its Plan-17c dry-run,
  // the product CSV import, and image uploads. `apiFetchRaw` already forwards a FormData
  // untouched so fetch can generate the boundary — it was simply never handed one.
  //
  // Replay on the 401-retry below stays safe: a FormData's Blob parts are re-readable, so
  // the second attempt sends the same file rather than an exhausted stream.
  const contentType = req.headers.get("content-type") ?? "";
  let body: FormData | Record<string, unknown> | undefined;
  if (!(req.method === "GET" || req.method === "DELETE" || req.method === "HEAD")) {
    if (contentType.startsWith("multipart/form-data")) {
      try {
        body = await req.formData();
      } catch {
        // A malformed upload is the caller's problem to see, not a 500 from the proxy.
        return json({ detail: "Request body is not valid multipart form data." }, 400);
      }
    } else {
      // An unparseable NON-EMPTY body is an error, not an empty object. The old
      // `.catch(() => ({}))` covered both cases at once, which is how a discarded file
      // became a confusing 415 from Django instead of a complaint from here.
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
  }

  let token: string;
  try {
    token =
      decision.kind === "authenticated"
        ? decision.token
        : await refreshAndPersist(jar, jar.get(REFRESH_COOKIE)!.value);
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 400 || e.status === 401) clearSession(jar);
      return json({ detail: "Session expired. Sign in again." }, 401);
    }
    return json({ detail: "The API is not responding." }, 502);
  }

  let res: Response;
  try {
    res = await apiFetchRaw(target, { method: req.method, body, token });
  } catch {
    // The API is unreachable (down, DNS, timeout). 502 rather than letting the throw
    // become an opaque 500: the admin UI can tell "the backend is down" from "you may not
    // do that", and a 500 here would send whoever is on call reading this app's logs
    // instead of Django's.
    return json({ detail: "The API is not responding." }, 502);
  }

  // One silent renewal on a rejected access token, then one retry. Request-body replay is
  // safe only because `apiFetchRaw` re-serialises `body` to JSON on each attempt; if
  // streaming request bodies are ever added, this retry must be disabled for them.
  if (res.status === 401) {
    const refresh = jar.get(REFRESH_COOKIE)?.value;
    if (refresh) {
      // DRAINED, never `body.cancel()` — Next tees response bodies for its cache layer and
      // an awaited cancel() on one branch blocks until undici's ~300s timeout.
      await drainBody(res);
      try {
        const fresh = await refreshAndPersist(jar, refresh);
        res = await apiFetchRaw(target, { method: req.method, body, token: fresh });
      } catch (e) {
        if (e instanceof ApiError) {
          if (e.status === 400 || e.status === 401) clearSession(jar);
          return json({ detail: "Session expired. Sign in again." }, 401);
        }
        return json({ detail: "The API is not responding." }, 502);
      }
    }
  }

  const text = await res.text();
  return new Response(text || null, {
    status: res.status,
    headers: {
      ...NO_STORE,
      "content-type": res.headers.get("content-type") ?? "application/json",
    },
  });
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
