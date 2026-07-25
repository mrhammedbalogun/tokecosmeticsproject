import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";
import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "content-type": "application/json" },
  });
}

/** Re-verify a payment on customer return / inline callback (Plan-14b). Authed; the
 * backend scopes the payment to the requesting user's own orders (404 otherwise), so
 * a guessed reference can't leak another shopper's order. */
export async function POST(req: Request) {
  const jar = await cookies();
  if (!jar.get(ACCESS_COOKIE)?.value && !jar.get(REFRESH_COOKIE)?.value) {
    return json({ detail: "Not authenticated." }, 401);
  }
  const body = await req.json().catch(() => ({}));
  const reference = typeof body.reference === "string" ? body.reference : "";
  if (!reference) return json({ detail: "Missing reference." }, 400);
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  try {
    const out = await fetchWithAuth(
      `/payments/${encodeURIComponent(reference)}/verify/`,
      { method: "POST", country, body: {} },
    );
    return json(out, 200);
  } catch (e) {
    if (e instanceof ApiError) return json(e.data ?? { detail: "Upstream error." }, e.status);
    return json({ detail: "Unexpected error." }, 500);
  }
}
