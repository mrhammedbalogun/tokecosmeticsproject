import { cookies } from "next/headers";
import { apiFetch, ApiError, type ApiFetchOptions } from "@/lib/api";
import { ACCESS_COOKIE, REFRESH_COOKIE, ACCESS_MAX_AGE, cookieOptions } from "@/lib/auth";

/** Read the current access token (server-only). */
export async function getAccessToken(): Promise<string | undefined> {
  return (await cookies()).get(ACCESS_COOKIE)?.value;
}

/**
 * Authenticated server-side fetch with a single silent refresh: if the access token
 * is rejected (401), swap the refresh token for a fresh access token, persist it, and
 * retry once. Used by Server Components that need the logged-in user.
 */
export async function fetchWithAuth<T = unknown>(
  path: string,
  opts: ApiFetchOptions = {},
): Promise<T> {
  const jar = await cookies();
  const token = jar.get(ACCESS_COOKIE)?.value;
  try {
    return await apiFetch<T>(path, { ...opts, token });
  } catch (e) {
    if (!(e instanceof ApiError) || e.status !== 401) throw e;
    const refresh = jar.get(REFRESH_COOKIE)?.value;
    if (!refresh) throw e;
    const out = await apiFetch<{ access: string }>("/auth/token/refresh/", {
      method: "POST", body: { refresh },
    });
    jar.set(ACCESS_COOKIE, out.access, cookieOptions({ maxAge: ACCESS_MAX_AGE }));
    return apiFetch<T>(path, { ...opts, token: out.access });
  }
}
