import { cookies } from "next/headers";
import { apiFetch, ApiError } from "@/lib/api";
import {
  ACCESS_COOKIE, CART_COOKIE, REFRESH_COOKIE, ACCESS_MAX_AGE, REFRESH_MAX_AGE, cookieOptions,
} from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

type Action = "login" | "register" | "logout" | "refresh" | "me";

type Jar = Awaited<ReturnType<typeof cookies>>;

/**
 * Fold the guest cart into the account that just authenticated.
 *
 * This lives HERE, not in the page that signed the user in, because it is a property of
 * authenticating rather than of any one surface. It used to live in checkout's
 * SignInStep, which meant every new sign-in surface had to remember to repeat it — and
 * a shopper who signed in from the header instead of checkout would silently lose their
 * bag. Doing it in the one place all authentication passes through means no future page
 * can omit it.
 *
 * It also removes a race the client version had: SignInStep snapshotted `cart.id` from
 * react-query state, so submitting before that query resolved merged nothing at all. The
 * cookie is the authoritative copy and is always readable here.
 *
 * Best-effort by design — see the call sites for why a failure must not surface.
 */
async function mergeGuestCart(jar: Jar, accessToken: string): Promise<void> {
  const guestCartId = jar.get(CART_COOKIE)?.value;
  if (!guestCartId) return;
  // The backend ignores foreign, claimed, converted and malformed ids (it filters on
  // `user__isnull=True`), and merging twice is a no-op — so a stale or hostile cookie
  // value cannot move someone else's cart into this account.
  try {
    const merged = await apiFetch<{ id?: string }>("/cart/merge/", {
      method: "POST",
      body: { cart_id: guestCartId },
      // The token straight from the login response, NOT jar.get(ACCESS_COOKIE): the jar
      // reflects the INCOMING request, so mid-handler it still holds the old (or no)
      // token — `jar.set` only stages a cookie on the outgoing response.
      token: accessToken,
      // Without this, apiFetch defaults X-Country to NG and the backend's get_or_create
      // would mint an NG cart for, say, a UK shopper who has no user cart yet.
      country: jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY,
    });
    // Point the browser at the surviving cart; the guest one is now converted.
    if (merged?.id) jar.set(CART_COOKIE, merged.id, cookieOptions());
  } catch {
    // Swallowed deliberately. The catch-all below converts an ApiError into a failure
    // response — if a merge error reached it, the user would be told the login failed
    // while actually being logged in, cookies and all.
  }
}

async function setTokens(access?: string, refresh?: string) {
  const jar = await cookies();
  if (access) jar.set(ACCESS_COOKIE, access, cookieOptions({ maxAge: ACCESS_MAX_AGE }));
  if (refresh) jar.set(REFRESH_COOKIE, refresh, cookieOptions({ maxAge: REFRESH_MAX_AGE }));
}
async function clearTokens() {
  const jar = await cookies();
  jar.delete(ACCESS_COOKIE);
  jar.delete(REFRESH_COOKIE);
  // Drop the cart pointer too, so a signed-out browser never carries a user-cart id.
  // Not a leak if it lingered (the backend ignores a cart that belongs to a user), but
  // it keeps the cookie's meaning strictly "the guest cart in this browser".
  jar.delete(CART_COOKIE);
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
        await mergeGuestCart(jar, tokens.access);
        return json({ ok: true });
      }
      case "register": {
        // Django register does NOT return tokens; create the account, then log in.
        await apiFetch("/auth/register/", { method: "POST", body });
        const tokens = await apiFetch<{ access: string; refresh: string }>("/auth/token/", {
          method: "POST", body: { email: body.email, password: body.password },
        });
        await setTokens(tokens.access, tokens.refresh);
        await mergeGuestCart(jar, tokens.access);
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
