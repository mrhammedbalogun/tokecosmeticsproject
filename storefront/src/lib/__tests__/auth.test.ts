import { describe, it, expect } from "vitest";
import {
  ACCESS_COOKIE, REFRESH_COOKIE, CART_COOKIE, ACCESS_MAX_AGE, REFRESH_MAX_AGE, cookieOptions,
} from "@/lib/auth";

/** Mirrors backend/config/settings/base.py SIMPLE_JWT. Kept here so the assertions below
 * name the numbers they are protecting rather than hiding them in a magic literal. */
const ACCESS_TOKEN_LIFETIME_SECONDS = 15 * 60; // timedelta(minutes=15)
const REFRESH_TOKEN_LIFETIME_SECONDS = 30 * 24 * 60 * 60; // timedelta(days=30)

describe("auth cookie contract", () => {
  it("names the token cookies", () => {
    expect(ACCESS_COOKIE).toBe("access");
    expect(REFRESH_COOKIE).toBe("refresh");
    expect(CART_COOKIE).toBe("cart_id");
  });

  it("token cookies are httpOnly, lax, path=/", () => {
    const o = cookieOptions();
    expect(o.httpOnly).toBe(true);
    expect(o.sameSite).toBe("lax");
    expect(o.path).toBe("/");
  });

  it("is secure in production, not in dev", () => {
    expect(cookieOptions({ nodeEnv: "production" }).secure).toBe(true);
    expect(cookieOptions({ nodeEnv: "development" }).secure).toBe(false);
  });

  it("passes through a maxAge", () => {
    expect(cookieOptions({ maxAge: 3600 }).maxAge).toBe(3600);
  });
});

/**
 * The cookie must expire BEFORE the token it carries, never after.
 *
 * The access cookie's lifetime is how the storefront decides whether a session looks
 * live: `decideAuth` treats "access cookie present" as authenticated, and
 * `decideLoginEntry` uses it to skip the login form. If the cookie outlives the JWT, then
 * for the whole overlap the browser holds a credential Django will reject — every gated
 * page renders, fetches, 401s, and bounces, and the login page's short-circuit sends an
 * already-signed-in user into a guaranteed 401 instead of straight to their destination.
 *
 * It was 30 minutes against a 15-minute token: wrong for HALF of every session.
 */
describe("cookie lifetimes track the backend's token lifetimes", () => {
  it("the access cookie expires before the access token does", () => {
    expect(ACCESS_MAX_AGE).toBeLessThan(ACCESS_TOKEN_LIFETIME_SECONDS);
  });

  it("but is not so short that it wastes a usable token", () => {
    // A pointlessly tiny value would bounce users through renewal constantly.
    expect(ACCESS_MAX_AGE).toBeGreaterThan(ACCESS_TOKEN_LIFETIME_SECONDS * 0.75);
  });

  it("the refresh cookie also expires no later than the refresh token", () => {
    expect(REFRESH_MAX_AGE).toBeLessThanOrEqual(REFRESH_TOKEN_LIFETIME_SECONDS);
  });
});
