/**
 * Single source of truth for the storefront's auth/cart cookies. The token cookies
 * MUST stay httpOnly so a JWT is never reachable from browser JS (XSS token theft).
 * Route Handlers set/clear them via these helpers — never hand-roll the flags.
 */
export const ACCESS_COOKIE = "access";
export const REFRESH_COOKIE = "refresh";
export const CART_COOKIE = "cart_id";

// Access tokens are short-lived; refresh long-lived. Match your SimpleJWT lifetimes.
export const ACCESS_MAX_AGE = 60 * 30; // 30 min
export const REFRESH_MAX_AGE = 60 * 60 * 24 * 14; // 14 days

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
