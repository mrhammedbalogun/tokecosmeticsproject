import { cookies } from "next/headers";
import { apiFetch, ApiError } from "@/lib/api";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import {
  clearTokens, establishSession, registerSession, setTokens,
} from "@/lib/auth-session";

type Action = "login" | "register" | "logout" | "refresh" | "me";

/**
 * The session mechanics (token cookies + the guest-cart merge) live in
 * `lib/auth-session.ts`, shared with the `/login` Server Action. They were moved out of
 * this file rather than copied: a Server Action cannot reuse this route by fetching it,
 * because `Set-Cookie` on a fetch response never reaches the outer response — so without
 * a shared module the merge would exist twice and drift.
 *
 * This route keeps its contract exactly as it was: checkout's `SignInStep` still posts
 * here, and Plan-15 must not touch checkout.
 */
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

export async function POST(req: Request, ctx: { params: Promise<{ action: string }> }) {
  const { action } = await ctx.params;
  const jar = await cookies();
  const body = await req.json().catch(() => ({}));

  try {
    switch (action as Action) {
      case "login": {
        await establishSession(jar, { email: body.email, password: body.password });
        return json({ ok: true });
      }
      case "register": {
        // Django register does NOT return tokens; registerSession creates the account and
        // then logs in. Shared with the /register Server Action so the two cannot drift.
        await registerSession(jar, body);
        return json({ ok: true }, 201);
      }
      case "logout": {
        const access = jar.get(ACCESS_COOKIE)?.value;
        const refresh = jar.get(REFRESH_COOKIE)?.value;
        if (refresh && access) {
          await apiFetch("/auth/logout/", { method: "POST", body: { refresh }, token: access })
            .catch(() => undefined); // best-effort blacklist; clear cookies regardless
        }
        clearTokens(jar);
        return json({ ok: true });
      }
      case "refresh": {
        const refresh = jar.get(REFRESH_COOKIE)?.value;
        if (!refresh) return json({ detail: "No session." }, 401);
        const out = await apiFetch<{ access: string; refresh?: string }>("/auth/token/refresh/", {
          method: "POST", body: { refresh },
        });
        setTokens(jar, out.access, out.refresh);
        // Deliberately NOT merging here: no identity transition, and refresh runs constantly.
        return json({ ok: true });
      }
      case "me": {
        const access = jar.get(ACCESS_COOKIE)?.value;
        if (!access) return json({ detail: "Not authenticated." }, 401);
        const me = await apiFetch("/auth/me/", { token: access });
        return json(me);
      }
      default:
        return json({ detail: "Unknown action." }, 404);
    }
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
