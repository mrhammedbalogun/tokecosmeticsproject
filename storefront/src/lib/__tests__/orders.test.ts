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
vi.mock("next/navigation", () => ({
  redirect: (to: string) => { throw new Redirected(to); },
}));

import { getOrder } from "@/lib/orders";

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
