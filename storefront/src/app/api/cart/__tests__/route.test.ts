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
