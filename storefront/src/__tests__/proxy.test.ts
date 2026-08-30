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
  it("seeds the NG default cookie when no cookie and no geo are present", async () => {
    const res = await run();
    expect(res.cookies.get("country")?.value).toBe("NG");
  });

  it("seeds the visitor's own market from geo on the first request", async () => {
    const res = await run({ "x-vercel-ip-country": "CA" });
    expect(res.cookies.get("country")?.value).toBe("CA");
  });

  it("seeds ZZ (international) for a geo country that is not a market", async () => {
    const res = await run({ "x-vercel-ip-country": "FR" });
    expect(res.cookies.get("country")?.value).toBe("ZZ");
  });

  it("injects the seeded market into the forwarded request cookies for the first render", async () => {
    // Without this, every cookies() reader falls back to NG for the very first paint —
    // the visitor's true market would only apply from their second request on.
    const res = await run({ "x-vercel-ip-country": "CA" });
    expect(res.headers.get("x-middleware-request-cookie")).toContain("country=CA");
  });

  it("preserves other request cookies when injecting the seed", async () => {
    const res = await run({ "x-vercel-ip-country": "CA", cookie: "cart=abc123" });
    const forwarded = res.headers.get("x-middleware-request-cookie");
    expect(forwarded).toContain("cart=abc123");
    expect(forwarded).toContain("country=CA");
  });

  it("does not overwrite an existing country cookie, even when geo disagrees", async () => {
    const res = await run({ cookie: "country=US", "x-vercel-ip-country": "CA" });
    // No Set-Cookie is emitted when the visitor already has a choice.
    expect(res.cookies.get("country")?.value).toBeUndefined();
  });

  it("forwards the platform geo header and ignores a client-spoofed one", async () => {
    // Vercel injects x-vercel-ip-country; a client tries to spoof x-geo-country directly.
    const res = await run({ "x-vercel-ip-country": "GB", "x-geo-country": "US" });
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
  it("redirects a visitor with no session to login, preserving where they were going", async () => {
    const res = await runAt("/account/orders");
    expect(location(res)).toBe("http://localhost:3000/login?next=%2Faccount%2Forders");
  });

  it("lets a visitor holding only a REFRESH cookie through", async () => {
    // THE 30-MINUTE TRAP. `access` lives 30 minutes, `refresh` 14 days. Gating on
    // `access` would bounce a perfectly logged-in user to /login every half hour, even
    // though their next request would have silently refreshed. Gate on `refresh`.
    const res = await runAt("/account/orders", { cookie: "refresh=r-token" });
    expect(location(res)).toBeNull();
  });

  it("lets a fully authenticated visitor through", async () => {
    const res = await runAt("/account", { cookie: "access=a-token; refresh=r-token" });
    expect(location(res)).toBeNull();
  });

  it("does not gate non-account routes", async () => {
    expect(location(await runAt("/products"))).toBeNull();
    expect(location(await runAt("/"))).toBeNull();
  });

  it("does not gate a route that merely starts with the same letters", async () => {
    // /accountants-special would otherwise be swept in by a naive startsWith("/account").
    expect(location(await runAt("/accountants-special"))).toBeNull();
  });

  it("still seeds the country cookie on a gated redirect", async () => {
    // The redirect must not cost a first-time visitor their market, or they come back
    // from login with no country and the wrong prices.
    const res = await runAt("/account");
    expect(res.cookies.get("country")?.value).toBe("NG");
  });
});

describe("proxy ad click ids (Plan-44)", () => {
  function landing(query: string, cookie = "") {
    return proxy(new NextRequest(`http://localhost:3000/${query}`, {
      headers: cookie ? { cookie } : {},
    }));
  }

  const GRANTED = `tc_consent=${encodeURIComponent(JSON.stringify({ v: 1, a: 1, m: 1 }))}`;
  const REFUSED = `tc_consent=${encodeURIComponent(JSON.stringify({ v: 1, a: 0, m: 0 }))}`;

  it("stores the click id for a visitor who has already consented", async () => {
    const res = await landing("?fbclid=FBCLICK&ttclid=TTCLICK", GRANTED);
    const stored = JSON.parse(decodeURIComponent(res.cookies.get("tc_clk")!.value));
    expect(stored.fbclid).toBe("FBCLICK");
    expect(stored.ttclid).toBe("TTCLICK");
    expect(typeof stored.ts).toBe("number");
  });

  it("stores NOTHING for a visitor who has not answered yet", async () => {
    // Storing first and deleting on refusal is the "set the cookie then ask" pattern
    // PECR exists to prohibit. The provider recovers the id from location.search.
    const res = await landing("?fbclid=FBCLICK");
    expect(res.cookies.get("tc_clk")).toBeUndefined();
  });

  it("stores nothing for a visitor who refused", async () => {
    const res = await landing("?fbclid=FBCLICK", REFUSED);
    expect(res.cookies.get("tc_clk")).toBeUndefined();
  });

  it("sets no click cookie on an ordinary navigation", async () => {
    const res = await landing("", GRANTED);
    expect(res.cookies.get("tc_clk")).toBeUndefined();
  });

  it("does not disturb the referral cookie", async () => {
    // The 2026-08-15 bogus-?ref= clobber came from attribution logic reaching across
    // itself. Click-id capture is additive and touches neither tc_ref nor its
    // normaliser — a landing with BOTH must still set the referral cookie correctly.
    const res = await landing("?ref=AMINA7K3P&fbclid=FBCLICK", GRANTED);
    expect(res.cookies.get("tc_ref")?.value).toBe("AMINA7K3P");
    expect(res.cookies.get("tc_clk")).toBeDefined();
  });

  it("leaves a referral-only landing with no click cookie at all", async () => {
    const res = await landing("?ref=AMINA7K3P", GRANTED);
    expect(res.cookies.get("tc_ref")?.value).toBe("AMINA7K3P");
    expect(res.cookies.get("tc_clk")).toBeUndefined();
  });
});
