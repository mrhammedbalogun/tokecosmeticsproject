import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>([["access", "OLD"], ["refresh", "RRR"]]);
const setSpy = vi.fn((n: string, v: string) => store.set(n, v));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => setSpy(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

class Redirected extends Error {
  constructor(public to: string) { super(`NEXT_REDIRECT ${to}`); }
}
class NotFound extends Error {
  constructor() { super("NEXT_NOT_FOUND"); }
}
vi.mock("next/navigation", () => ({
  redirect: (to: string) => { throw new Redirected(to); },
  notFound: () => { throw new NotFound(); },
}));

import { getOrder, getOrderOrNotFound } from "@/lib/orders";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  setSpy.mockClear();
  store.set("access", "OLD");
  store.set("refresh", "RRR");
});
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

describe("getOrder", () => {
  it("fetches the order and forwards the country", async () => {
    const f = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ number: "TC-100038" }), {
        status: 200, headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = f as unknown as typeof fetch;

    const order = await getOrder("TC-100038", "GB", "/checkout/confirmation/TC-100038");
    expect(order.number).toBe("TC-100038");
    expect(f.mock.calls[0][0]).toBe("http://backend:8000/api/v1/orders/TC-100038/");
    const init = f.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("X-Country")).toBe("GB");
  });

  it("URL-encodes the order number into the upstream path", async () => {
    // Migrated legacy numbers are not guaranteed URL-safe. Unencoded, "#" truncates the
    // path at the fragment and "/" invents a segment, so Django routes the request
    // elsewhere and the customer gets a 404 for an order that exists.
    const f = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ number: "TC#1/2" }), {
        status: 200, headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = f as unknown as typeof fetch;

    await getOrder("TC#1/2", "NG", "/account/orders/TC%231%2F2");
    expect(f.mock.calls[0][0]).toBe("http://backend:8000/api/v1/orders/TC%231%2F2/");
  });

  it("bounces a stale session through the renewal handler instead of refreshing in place", async () => {
    // The confirmation page is a Server Component, so getOrder must NEVER refresh here:
    // a rotation it cannot persist would blacklist the customer's refresh token and end
    // their session while the page still rendered normally. This is the C3 latent bug.
    const urls: string[] = [];
    global.fetch = vi.fn((url: string) => {
      urls.push(url);
      return Promise.resolve(new Response("{}", { status: 401 }));
    }) as unknown as typeof fetch;

    await expect(getOrder("TC-100038", "NG", "/checkout/confirmation/TC-100038")).rejects.toThrow(
      "NEXT_REDIRECT /api/auth/refresh-redirect?next=%2Fcheckout%2Fconfirmation%2FTC-100038",
    );
    expect(urls.some((u) => u.includes("/auth/token/refresh/"))).toBe(false);
    expect(setSpy).not.toHaveBeenCalled();
  });

  it("sends a caller with no session at all to login", async () => {
    store.delete("access");
    store.delete("refresh");
    global.fetch = vi.fn().mockResolvedValue(
      new Response("{}", { status: 403 }),
    ) as unknown as typeof fetch;

    // The backend 403s an anonymous caller without a tracking token (orders/views.py),
    // so there is no legitimate guest view of this page to protect.
    await expect(getOrder("TC-100038", "NG", "/checkout/confirmation/TC-100038")).rejects.toMatchObject({
      status: 403,
    });
  });
});

describe("getOrderOrNotFound", () => {
  const path = "/account/orders/TC-100038";
  const status = (code: number) => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response("{}", { status: code, headers: { "content-type": "application/json" } }),
    ) as unknown as typeof fetch;
  };

  it("returns the order on success", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ number: "TC-100038" }), {
        status: 200, headers: { "content-type": "application/json" },
      }),
    ) as unknown as typeof fetch;

    expect((await getOrderOrNotFound("TC-100038", "NG", path)).number).toBe("TC-100038");
  });

  // 403 as well as 404: orders/views.py owner-filters, so a 403 reaching the customer
  // would confirm that a stranger's order exists.
  it.each([[404], [403]])("maps %i to notFound()", async (code) => {
    status(code);

    await expect(getOrderOrNotFound("TC-100038", "NG", path)).rejects.toBeInstanceOf(NotFound);
  });

  it("lets the renewal bounce through instead of swallowing it", async () => {
    // The whole reason this wrapper does not catch-all: NEXT_REDIRECT is how the stale
    // session gets renewed, and eating it logs the customer out for good.
    status(401);

    await expect(getOrderOrNotFound("TC-100038", "NG", path)).rejects.toMatchObject({
      to: expect.stringContaining(encodeURIComponent(path)),
    });
  });

  it("rethrows a server error untouched rather than pretending the order is missing", async () => {
    status(500);

    await expect(getOrderOrNotFound("TC-100038", "NG", path)).rejects.toMatchObject({ status: 500 });
  });
});
