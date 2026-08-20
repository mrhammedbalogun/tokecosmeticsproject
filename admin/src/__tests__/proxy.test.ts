import { describe, it, expect } from "vitest";
import { NextRequest } from "next/server";
import { proxy } from "@/proxy";

/**
 * The router, not the gate. These tests exist for two reasons:
 *
 *  1. `proxy.ts` deliberately DUPLICATES the matrix rather than importing `decideAuth`
 *     (it may be deployed to a CDN edge, so it must stay dependency-free). Duplicated
 *     logic drifts unless something compares it, and this is that something.
 *  2. `Cache-Control: no-store` is set here for every matched route, and a missing
 *     no-store on an admin page is a PII finding waiting to happen.
 *
 * It is emphatically NOT proof of authorization. That lives in `lib/auth-guard.ts` (per
 * page and per BFF route) and, load-bearing, in Django.
 */
function request(path: string, cookies: Record<string, string> = {}) {
  const req = new NextRequest(`https://admin.test${path}`);
  for (const [name, value] of Object.entries(cookies)) req.cookies.set(name, value);
  return req;
}

const PAIR = { admin_access: "A", admin_refresh: "R" };
const PREAUTH = { admin_preauth: "P" };

function target(res: Response): string | null {
  const location = res.headers.get("location");
  return location ? new URL(location).pathname + new URL(location).search : null;
}

describe("no-store on everything it matches", () => {
  it("marks a page response no-store", () => {
    const res = proxy(request("/", PAIR));
    expect(res.headers.get("Cache-Control")).toContain("no-store");
  });
  it("marks a redirect no-store too", () => {
    const res = proxy(request("/orders"));
    expect(res.headers.get("Cache-Control")).toContain("no-store");
  });
  it("marks a BFF response no-store", () => {
    const res = proxy(request("/api/orders/", PAIR));
    expect(res.headers.get("Cache-Control")).toContain("no-store");
  });
});

describe("the router mirrors the gate matrix", () => {
  it("no cookies: app routes go to /login with a next=", () => {
    expect(target(proxy(request("/orders?page=2")))).toBe(
      `/login?next=${encodeURIComponent("/orders?page=2")}`,
    );
  });

  it("no cookies: /login renders, /totp does not", () => {
    expect(target(proxy(request("/login")))).toBeNull();
    expect(target(proxy(request("/totp")))).toBe("/login");
  });

  it("preauth only: app routes go to the TOTP step, NOT to /login", () => {
    expect(target(proxy(request("/orders", PREAUTH)))).toBe("/totp");
    expect(target(proxy(request("/login", PREAUTH)))).toBe("/totp");
    expect(target(proxy(request("/totp", PREAUTH)))).toBeNull();
  });

  it("session: app routes render, /login and /totp bounce to the dashboard", () => {
    expect(target(proxy(request("/orders", PAIR)))).toBeNull();
    expect(target(proxy(request("/login", PAIR)))).toBe("/");
    expect(target(proxy(request("/totp", PAIR)))).toBe("/");
  });

  it("refresh cookie alone still counts as a session — the renewal bounce is the page's job", () => {
    expect(target(proxy(request("/orders", { admin_refresh: "R" })))).toBeNull();
  });

  it("anomaly: every page route goes to the PURGE handler, not to /login", () => {
    // Redirecting to /login would loop: /login is gated too, sees the same anomaly, and
    // bounces again — and nothing in that cycle can delete a cookie, because a Server
    // Component may not. Caught by walking the matrix over real HTTP against a production
    // build, where it showed up as an infinite redirect and a 500.
    const both = { ...PAIR, ...PREAUTH };
    for (const path of ["/orders", "/login", "/totp", "/accept-invite?token=x"]) {
      expect(target(proxy(request(path, both)))).toBe("/api/auth/purge");
    }
  });

  it("anomaly: the redirect itself already expires all three cookies", () => {
    const res = proxy(request("/orders", { ...PAIR, ...PREAUTH }));
    for (const name of ["admin_access", "admin_refresh", "admin_preauth"]) {
      expect(res.cookies.get(name)?.value).toBe("");
    }
  });

  it("anomaly: a BFF call is NOT redirected — its handler answers 401 and purges", () => {
    // A fetch() that followed a redirect to /login would receive an HTML page where it
    // expected JSON, and the cookies would never be cleared.
    const both = { ...PAIR, ...PREAUTH };
    expect(target(proxy(request("/api/orders", both)))).toBeNull();
  });

  it("the accept-invite page is public in every ordinary state", () => {
    expect(target(proxy(request("/accept-invite?token=x")))).toBeNull();
    expect(target(proxy(request("/accept-invite?token=x", PREAUTH)))).toBeNull();
    expect(target(proxy(request("/accept-invite?token=x", PAIR)))).toBeNull();
  });

  it("never redirects a BFF call — Route Handlers answer with status codes", () => {
    expect(target(proxy(request("/api/orders/")))).toBeNull();
    expect(target(proxy(request("/api/orders/", PREAUTH)))).toBeNull();
  });

  it("does not mistake a prefix collision for a special route", () => {
    // `/login-help` is an ordinary admin page and must be gated like one.
    expect(target(proxy(request("/login-help")))).toBe(
      `/login?next=${encodeURIComponent("/login-help")}`,
    );
    expect(target(proxy(request("/totp-reset")))).toBe(
      `/login?next=${encodeURIComponent("/totp-reset")}`,
    );
  });
});

describe("the partner portal's own mini-matrix (Plan-39)", () => {
  const PARTNER = { partner_access: "PA", partner_refresh: "PR" };

  it("no partner cookies: portal pages go to the PARTNER login, never the staff one", () => {
    expect(target(proxy(request("/partner")))).toBe("/partner/login");
    expect(target(proxy(request("/partner/anything")))).toBe("/partner/login");
  });

  it("partner session: the portal renders and its login bounces home", () => {
    expect(target(proxy(request("/partner", PARTNER)))).toBeNull();
    expect(target(proxy(request("/partner/login", PARTNER)))).toBe("/partner");
    // The refresh cookie alone still counts, same as the staff matrix.
    expect(target(proxy(request("/partner", { partner_refresh: "PR" })))).toBeNull();
  });

  it("the two credential sets never cross: staff cookies do not open the portal, partner cookies do not open the admin", () => {
    expect(target(proxy(request("/partner", PAIR)))).toBe("/partner/login");
    expect(target(proxy(request("/orders", PARTNER)))).toBe(
      `/login?next=${encodeURIComponent("/orders")}`,
    );
  });

  it("the public price list renders for everyone — no cookies, any cookies", () => {
    expect(target(proxy(request("/partner/rates")))).toBeNull();
    expect(target(proxy(request("/partner/rates", PARTNER)))).toBeNull();
    expect(target(proxy(request("/partner/rates", PAIR)))).toBeNull();
    // A prefix collision is still gated: only the rates page itself is public.
    expect(target(proxy(request("/partner/rates-editor")))).toBe("/partner/login");
  });

  it("a prefix collision is not the portal", () => {
    expect(target(proxy(request("/partnership")))).toBe(
      `/login?next=${encodeURIComponent("/partnership")}`,
    );
  });

  it("portal responses are no-store like everything else here", () => {
    expect(proxy(request("/partner", PARTNER)).headers.get("Cache-Control")).toContain(
      "no-store",
    );
  });
});
