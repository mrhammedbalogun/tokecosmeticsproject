import { describe, it, expect } from "vitest";
import { ACCESS_COOKIE, REFRESH_COOKIE, CART_COOKIE, cookieOptions } from "@/lib/auth";

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
