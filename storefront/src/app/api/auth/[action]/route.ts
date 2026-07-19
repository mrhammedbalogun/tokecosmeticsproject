import { cookies } from "next/headers";
import { apiFetch, ApiError } from "@/lib/api";
import {
  ACCESS_COOKIE, REFRESH_COOKIE, ACCESS_MAX_AGE, REFRESH_MAX_AGE, cookieOptions,
} from "@/lib/auth";

type Action = "login" | "register" | "logout" | "refresh" | "me";

async function setTokens(access?: string, refresh?: string) {
  const jar = await cookies();
  if (access) jar.set(ACCESS_COOKIE, access, cookieOptions({ maxAge: ACCESS_MAX_AGE }));
  if (refresh) jar.set(REFRESH_COOKIE, refresh, cookieOptions({ maxAge: REFRESH_MAX_AGE }));
}
async function clearTokens() {
  const jar = await cookies();
  jar.delete(ACCESS_COOKIE);
  jar.delete(REFRESH_COOKIE);
}
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
        const tokens = await apiFetch<{ access: string; refresh: string }>("/auth/token/", {
          method: "POST", body,
        });
        await setTokens(tokens.access, tokens.refresh);
        return json({ ok: true });
      }
      case "register": {
        // Django register does NOT return tokens; create the account, then log in.
        await apiFetch("/auth/register/", { method: "POST", body });
        const tokens = await apiFetch<{ access: string; refresh: string }>("/auth/token/", {
          method: "POST", body: { email: body.email, password: body.password },
        });
        await setTokens(tokens.access, tokens.refresh);
        return json({ ok: true }, 201);
      }
      case "logout": {
        const access = jar.get(ACCESS_COOKIE)?.value;
        const refresh = jar.get(REFRESH_COOKIE)?.value;
        if (refresh && access) {
          await apiFetch("/auth/logout/", { method: "POST", body: { refresh }, token: access })
            .catch(() => undefined); // best-effort blacklist; clear cookies regardless
        }
        await clearTokens();
        return json({ ok: true });
      }
      case "refresh": {
        const refresh = jar.get(REFRESH_COOKIE)?.value;
        if (!refresh) return json({ detail: "No session." }, 401);
        const out = await apiFetch<{ access: string; refresh?: string }>("/auth/token/refresh/", {
          method: "POST", body: { refresh },
        });
        await setTokens(out.access, out.refresh);
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
