import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

/**
 * THE test for this layer. The generic proxy must read `admin_access` and nothing else —
 * a helper that "helpfully" reaches for whichever token cookie exists would forward a
 * PREAUTH token, a credential defined to open exactly three TOTP endpoints, to arbitrary
 * admin endpoints. It is this app's version of the class that ignored the claim it
 * declared, and it is asserted behaviourally: nothing is sent upstream at all.
 */
const store = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

import { GET, POST } from "../route";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.clear();
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

function ctx(path: string[]) {
  return { params: Promise.resolve({ path }) };
}

function ok(bodyText = "{}", status = 200) {
  return new Response(bodyText, { status, headers: { "content-type": "application/json" } });
}

describe("the generic proxy never forwards a preauth token", () => {
  it("answers 401 for a preauth-only request and makes NO upstream call", async () => {
    store.set("admin_preauth", "PREAUTH-TOKEN");
    const fetchSpy = vi.fn(() => Promise.resolve(ok()));
    global.fetch = fetchSpy as unknown as typeof fetch;

    const res = await GET(new Request("http://admin.test/api/orders/"), ctx(["orders"]));

    expect(res.status).toBe(401);
    // Not "did not send the preauth token" — did not call the API at all. A helper that
    // fell back would have produced a request here.
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("answers 401 with no cookies at all, and still makes no upstream call", async () => {
    const fetchSpy = vi.fn(() => Promise.resolve(ok()));
    global.fetch = fetchSpy as unknown as typeof fetch;

    const res = await GET(new Request("http://admin.test/api/orders/"), ctx(["orders"]));

    expect(res.status).toBe(401);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("the anomaly row: preauth alongside a session pair", () => {
  it("purges every cookie and 401s rather than forwarding the access token it holds", async () => {
    store.set("admin_access", "ACCESS");
    store.set("admin_refresh", "REFRESH");
    store.set("admin_preauth", "PREAUTH");
    const fetchSpy = vi.fn(() => Promise.resolve(ok()));
    global.fetch = fetchSpy as unknown as typeof fetch;

    const res = await GET(new Request("http://admin.test/api/orders/"), ctx(["orders"]));

    expect(res.status).toBe(401);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(store.has("admin_access")).toBe(false);
    expect(store.has("admin_refresh")).toBe(false);
    expect(store.has("admin_preauth")).toBe(false);
  });
});

describe("the happy path", () => {
  it("forwards the admin access token, the method, the body and the query string", async () => {
    store.set("admin_access", "ACCESS");
    store.set("admin_refresh", "REFRESH");
    const calls: Array<[string, RequestInit | undefined]> = [];
    global.fetch = vi.fn((url: string, init?: RequestInit) => {
      calls.push([url, init]);
      return Promise.resolve(ok(JSON.stringify({ ok: true })));
    }) as unknown as typeof fetch;

    const req = new Request("http://admin.test/api/admin/staff/invites/?page=2", {
      method: "POST",
      body: JSON.stringify({ email: "a@b.com" }),
      headers: { "content-type": "application/json" },
    });
    const res = await POST(req, ctx(["admin", "staff", "invites"]));

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    expect(calls[0][0]).toBe("http://backend:8000/api/v1/admin/staff/invites/?page=2");
    expect(calls[0][1]?.method).toBe("POST");
    expect(new Headers(calls[0][1]?.headers).get("Authorization")).toBe("Bearer ACCESS");
    expect(calls[0][1]?.body).toBe(JSON.stringify({ email: "a@b.com" }));
  });

  it("SENDS A FILE-EXTENSION ENDPOINT WITHOUT A TRAILING SLASH", async () => {
    // `orders/export.csv` and `orders/<number>/invoice.pdf` are registered in Django
    // without a trailing slash, so `orders/<str:number>/` cannot swallow them. Appending
    // one made both match the detail route as an order literally numbered "export.csv"
    // and 404 in the browser, while every mocked test here passed.
    store.set("admin_access", "ACCESS");
    const calls: string[] = [];
    global.fetch = vi.fn((url: string) => {
      calls.push(url);
      return Promise.resolve(ok());
    }) as unknown as typeof fetch;

    await GET(
      new Request("http://admin.test/api/admin/orders/export.csv"),
      ctx(["admin", "orders", "export.csv"]),
    );
    await GET(
      new Request("http://admin.test/api/admin/orders/TC-100044/invoice.pdf"),
      ctx(["admin", "orders", "TC-100044", "invoice.pdf"]),
    );

    expect(calls[0]).toBe("http://backend:8000/api/v1/admin/orders/export.csv");
    expect(calls[1]).toBe("http://backend:8000/api/v1/admin/orders/TC-100044/invoice.pdf");
  });

  it("still slashes an ordinary segment that merely contains a dot", async () => {
    store.set("admin_access", "ACCESS");
    const calls: string[] = [];
    global.fetch = vi.fn((url: string) => {
      calls.push(url);
      return Promise.resolve(ok());
    }) as unknown as typeof fetch;

    await GET(
      new Request("http://admin.test/api/admin/customers/a.b@c.example"),
      ctx(["admin", "customers", "a.b@c.example"]),
    );

    expect(calls[0]).toBe("http://backend:8000/api/v1/admin/customers/a.b%40c.example/");
  });

  it("marks every response no-store", async () => {
    store.set("admin_access", "ACCESS");
    global.fetch = vi.fn(() => Promise.resolve(ok())) as unknown as typeof fetch;
    const res = await GET(new Request("http://admin.test/api/orders/"), ctx(["orders"]));
    expect(res.headers.get("cache-control")).toContain("no-store");
  });

  it("passes a backend error status and body straight through", async () => {
    store.set("admin_access", "ACCESS");
    global.fetch = vi.fn(() =>
      Promise.resolve(ok(JSON.stringify({ detail: "You do not have permission." }), 403)),
    ) as unknown as typeof fetch;

    const res = await GET(new Request("http://admin.test/api/orders/"), ctx(["orders"]));
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ detail: "You do not have permission." });
  });

  it("refuses traversal segments without calling upstream", async () => {
    store.set("admin_access", "ACCESS");
    const fetchSpy = vi.fn(() => Promise.resolve(ok()));
    global.fetch = fetchSpy as unknown as typeof fetch;
    const res = await GET(new Request("http://admin.test/api/x/"), ctx(["..", "etc"]));
    expect(res.status).toBe(400);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("renewal", () => {
  it("renews inline when only the refresh cookie survives, then forwards", async () => {
    store.set("admin_refresh", "REFRESH");
    const calls: string[] = [];
    global.fetch = vi.fn((url: string) => {
      calls.push(url);
      if (url.endsWith("/auth/token/refresh/")) {
        return Promise.resolve(
          ok(JSON.stringify({ access: "NEW-ACCESS", refresh: "NEW-REFRESH" })),
        );
      }
      return Promise.resolve(ok(JSON.stringify({ ok: true })));
    }) as unknown as typeof fetch;

    const res = await GET(new Request("http://admin.test/api/orders/"), ctx(["orders"]));

    expect(res.status).toBe(200);
    expect(calls[0]).toContain("/auth/token/refresh/");
    // The ROTATED refresh must be persisted: the spent one is blacklisted server-side.
    expect(store.get("admin_refresh")).toBe("NEW-REFRESH");
    expect(store.get("admin_access")).toBe("NEW-ACCESS");
  });

  it("renews once on a 401 from the backend and retries", async () => {
    store.set("admin_access", "STALE");
    store.set("admin_refresh", "REFRESH");
    let seenStale = false;
    global.fetch = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/auth/token/refresh/")) {
        return Promise.resolve(ok(JSON.stringify({ access: "NEW", refresh: "NEWR" })));
      }
      if (new Headers(init?.headers).get("Authorization") === "Bearer STALE") {
        seenStale = true;
        return Promise.resolve(ok("{}", 401));
      }
      return Promise.resolve(ok(JSON.stringify({ ok: true })));
    }) as unknown as typeof fetch;

    const res = await GET(new Request("http://admin.test/api/orders/"), ctx(["orders"]));

    expect(seenStale).toBe(true);
    expect(res.status).toBe(200);
    expect(store.get("admin_access")).toBe("NEW");
  });

  it("clears the session when the refresh token itself is rejected", async () => {
    store.set("admin_refresh", "DEAD");
    global.fetch = vi.fn(() =>
      Promise.resolve(ok(JSON.stringify({ detail: "Token is invalid" }), 401)),
    ) as unknown as typeof fetch;

    const res = await GET(new Request("http://admin.test/api/orders/"), ctx(["orders"]));

    expect(res.status).toBe(401);
    expect(store.has("admin_refresh")).toBe(false);
  });
});
