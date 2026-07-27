/**
 * Single source of truth for the storefront's auth/cart cookies. The token cookies
 * MUST stay httpOnly so a JWT is never reachable from browser JS (XSS token theft).
 * Route Handlers set/clear them via these helpers — never hand-roll the flags.
 */
export const ACCESS_COOKIE = "access";
export const REFRESH_COOKIE = "refresh";
export const CART_COOKIE = "cart_id";

// Access tokens are short-lived; refresh long-lived. These MUST expire no later than the
// tokens they carry (backend SIMPLE_JWT: access 15 min, refresh 30 days) — the cookie's
// presence is what `decideAuth` and `decideLoginEntry` read as "this session is live", so
// a cookie that outlives its token means the storefront confidently presents a credential
// Django rejects. It was 30 min against a 15-min token: wrong for half of every session,
// which made the login short-circuit's happy path a guaranteed 401. One minute of slack
// covers clock skew between the browser and the API.
export const ACCESS_MAX_AGE = 60 * 14; // 14 min, under the 15-min access token
export const REFRESH_MAX_AGE = 60 * 60 * 24 * 14; // 14 days, well under the 30-day token

export interface CookieOptions {
  httpOnly: boolean;
  sameSite: "lax";
  secure: boolean;
  path: string;
  maxAge?: number;
}

export function cookieOptions(
  opts: { nodeEnv?: string; maxAge?: number } = {},
): CookieOptions {
  const env = opts.nodeEnv ?? process.env.NODE_ENV;
  return {
    httpOnly: true,
    sameSite: "lax",
    secure: env === "production",
    path: "/",
    ...(opts.maxAge !== undefined ? { maxAge: opts.maxAge } : {}),
  };
}
