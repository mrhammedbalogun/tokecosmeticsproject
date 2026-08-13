import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>();
const setSpy = vi.fn((n: string, v: string) => store.set(n, v));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => setSpy(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

import { GET, POST } from "@/app/api/cart/[[...path]]/route";

const CART = { id: "11111111-1111-1111-1111-111111111111", items: [], subtotal: "0.00", currency: "NGN" };
const originalFetch = global.fetch;
beforeEach(() => { store.clear(); setSpy.mockClear(); process.env.API_URL = "http://backend:8000"; });
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function upstream(body: unknown, status = 200) {
  global.fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  ) as unknown as typeof fetch;
  return global.fetch as unknown as ReturnType<typeof vi.fn>;
}

describe("cart BFF", () => {
  it("GET forwards X-Country and persists the returned cart id into the cookie", async () => {
    store.set("country", "GB");
    const f = upstream(CART);
    const res = await GET(new Request("http://localhost:3000/api/cart"), { params: Promise.resolve({ path: [] }) });
    expect(res.status).toBe(200);
    const init = f.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("X-Country")).toBe("GB");
    expect(setSpy).toHaveBeenCalledWith("cart_id", CART.id);
  });

  it("GET forwards an existing cart_id cookie as X-Cart-Id", async () => {
    store.set("cart_id", "22222222-2222-2222-2222-222222222222");
    const f = upstream(CART);
    await GET(new Request("http://localhost:3000/api/cart"), { params: Promise.resolve({ path: [] }) });
    const init = f.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("X-Cart-Id")).toBe("22222222-2222-2222-2222-222222222222");
  });

  it("refreshes a rejected access token and retries — the cart must not go anonymous", async () => {
    // The original bug: the route read the access cookie raw, so 14 minutes into a
    // session cart requests silently went out unauthenticated and the backend
    // answered with a fresh empty guest cart ("my cart emptied itself").
    store.set("access", "stale-token");
    store.set("refresh", "refresh-token");
    const f = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "expired" }), {
        status: 401, headers: { "content-type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ access: "fresh-token" }), {
        status: 200, headers: { "content-type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify(CART), {
        status: 200, headers: { "content-type": "application/json" },
      }));
    global.fetch = f as unknown as typeof fetch;

    const res = await GET(new Request("http://localhost:3000/api/cart"), { params: Promise.resolve({ path: [] }) });

    expect(res.status).toBe(200);
    expect((f.mock.calls[1][0] as string).endsWith("/auth/token/refresh/")).toBe(true);
    const retry = new Headers((f.mock.calls[2][1] as RequestInit).headers);
    expect(retry.get("Authorization")).toBe("Bearer fresh-token");
    expect(setSpy).toHaveBeenCalledWith("access", "fresh-token");
  });

  it("POST items proxies the body to /cart/items/", async () => {
    const f = upstream(CART);
    const res = await POST(
      new Request("http://localhost:3000/api/cart/items", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ variant_id: 10, quantity: 2 }),
      }),
      { params: Promise.resolve({ path: ["items"] }) },
    );
    expect(res.status).toBe(200);
    const url = f.mock.calls[0][0] as string;
    expect(url).toBe("http://backend:8000/api/v1/cart/items/");
    const init = f.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ variant_id: 10, quantity: 2 });
  });
});
