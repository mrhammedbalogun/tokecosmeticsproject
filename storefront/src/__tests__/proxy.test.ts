import { describe, it, expect } from "vitest";
import { NextRequest } from "next/server";
import { proxy } from "@/proxy";

function run(headers: Record<string, string> = {}) {
  return proxy(new NextRequest("http://localhost:3000/", { headers }));
}

function runAt(path: string, headers: Record<string, string> = {}) {
  return proxy(new NextRequest(`http://localhost:3000${path}`, { headers }));
}

function location(res: ReturnType<typeof proxy>) {
  return res.headers.get("location");
}

describe("proxy country + geo", () => {
  it("seeds the NG default cookie when no cookie and no geo are present", () => {
    const res = run();
    expect(res.cookies.get("country")?.value).toBe("NG");
  });

  it("seeds the visitor's own market from geo on the first request", () => {
    const res = run({ "x-vercel-ip-country": "CA" });
    expect(res.cookies.get("country")?.value).toBe("CA");
  });

  it("seeds ZZ (international) for a geo country that is not a market", () => {
    const res = run({ "x-vercel-ip-country": "FR" });
    expect(res.cookies.get("country")?.value).toBe("ZZ");
  });

  it("injects the seeded market into the forwarded request cookies for the first render", () => {
    // Without this, every cookies() reader falls back to NG for the very first paint —
    // the visitor's true market would only apply from their second request on.
    const res = run({ "x-vercel-ip-country": "CA" });
    expect(res.headers.get("x-middleware-request-cookie")).toContain("country=CA");
  });

  it("preserves other request cookies when injecting the seed", () => {
    const res = run({ "x-vercel-ip-country": "CA", cookie: "cart=abc123" });
    const forwarded = res.headers.get("x-middleware-request-cookie");
    expect(forwarded).toContain("cart=abc123");
    expect(forwarded).toContain("country=CA");
  });

  it("does not overwrite an existing country cookie, even when geo disagrees", () => {
    const res = run({ cookie: "country=US", "x-vercel-ip-country": "CA" });
    // No Set-Cookie is emitted when the visitor already has a choice.
    expect(res.cookies.get("country")?.value).toBeUndefined();
  });

  it("forwards the platform geo header and ignores a client-spoofed one", () => {
    // Vercel injects x-vercel-ip-country; a client tries to spoof x-geo-country directly.
    const res = run({ "x-vercel-ip-country": "GB", "x-geo-country": "US" });
    // The forwarded (overridden) request header must reflect the trusted platform value.
    // The `x-middleware-request-*` prefix is a Next.js internal encoding for forwarded request
    // headers — if this breaks on a Next upgrade, the test is what changed, not the proxy.
    expect(res.headers.get("x-middleware-request-x-geo-country")).toBe("GB");
  });
});

/**
 * The proxy's account check is a cheap PRESENCE hint, not authorization — it cannot
 * verify a token (Node runtime, no shared modules, may run at the CDN edge). Its only
 * jobs are to stop rendering eight dynamic pages for an obviously logged-out visitor
 * and to attach a correct `?next=` on a direct URL hit. The real gate is each page's
 * own data fetch.
 */
describe("proxy account gate", () => {
  it("redirects a visitor with no session to login, preserving where they were going", () => {
    const res = runAt("/account/orders");
    expect(location(res)).toBe("http://localhost:3000/login?next=%2Faccount%2Forders");
  });

  it("lets a visitor holding only a REFRESH cookie through", () => {
    // THE 30-MINUTE TRAP. `access` lives 30 minutes, `refresh` 14 days. Gating on
    // `access` would bounce a perfectly logged-in user to /login every half hour, even
    // though their next request would have silently refreshed. Gate on `refresh`.
    const res = runAt("/account/orders", { cookie: "refresh=r-token" });
    expect(location(res)).toBeNull();
  });

  it("lets a fully authenticated visitor through", () => {
    const res = runAt("/account", { cookie: "access=a-token; refresh=r-token" });
    expect(location(res)).toBeNull();
  });

  it("does not gate non-account routes", () => {
    expect(location(runAt("/products"))).toBeNull();
    expect(location(runAt("/"))).toBeNull();
  });

  it("does not gate a route that merely starts with the same letters", () => {
    // /accountants-special would otherwise be swept in by a naive startsWith("/account").
    expect(location(runAt("/accountants-special"))).toBeNull();
  });

  it("still seeds the country cookie on a gated redirect", () => {
    // The redirect must not cost a first-time visitor their market, or they come back
    // from login with no country and the wrong prices.
    const res = runAt("/account");
    expect(res.cookies.get("country")?.value).toBe("NG");
  });
});
