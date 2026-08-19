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

// The guest cart id is not a credential — it just names a cart row. It must OUTLIVE the
// browser session (a shopper who closes the tab expects their cart back days later), so
// unlike the token cookies it gets a long fixed max-age. The backend revives abandoned
// carts on return, so the only hard limit on cart recall is this cookie's lifetime.
export const CART_MAX_AGE = 60 * 60 * 24 * 30; // 30 days

// The guest-order token (Plan-38) IS a credential: it opens the FULL order view and
// payment verify for the one order it names. It exists only in this httpOnly cookie —
// minted on the guest's own checkout 201, stripped from the browser response, never in
// a gateway return URL (Paystack's dashboard-callback fallback drops our query string,
// so a URL-borne token would fail exactly the customer who just paid). One cookie, not
// one per order: a guest placing a second order overwrites it, and the older order is
// still reachable through its emailed tracking link. 7 days matches the backend
// GUEST_ORDER_MAX_AGE (orders/tokens.py).
export const GUEST_ORDER_COOKIE = "guest_order";
export const GUEST_ORDER_MAX_AGE = 60 * 60 * 24 * 7; // 7 days, matches the token TTL

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
