import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>([["access", "TOK"], ["country", "NG"]]);
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

import { POST } from "@/app/api/checkout/buy-now/route";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.set("access", "TOK"); store.set("country", "NG");
});
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function upstream(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), {
    status, headers: { "content-type": "application/json" },
  }));
  global.fetch = f as unknown as typeof fetch;
  return f;
}
const req = (body: unknown) => new Request("http://localhost:3000/api/checkout/buy-now", {
  method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
});

describe("buy-now BFF", () => {
  it("forwards variant+qty with Bearer and country; returns the express cart", async () => {
    const f = upstream(200, { id: "c1", kind: "express", items: [{ variant_id: 5 }] });
    const res = await POST(req({ variant_id: 5, quantity: 2 }));
    expect(res.status).toBe(200);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://backend:8000/api/v1/checkout/buy-now/");
    const h = new Headers((init as RequestInit).headers);
    expect(h.get("Authorization")).toBe("Bearer TOK");
    expect(h.get("X-Country")).toBe("NG");
    expect((await res.json()).kind).toBe("express");
  });

  it("401 without a session, no upstream call (guest flow is client-side, D6)", async () => {
    store.delete("access"); store.delete("refresh");
    const f = upstream(200, {});
    const res = await POST(req({ variant_id: 5, quantity: 1 }));
    expect(res.status).toBe(401);
    expect(f).not.toHaveBeenCalled();
  });

  it("rejects a missing variant_id with 400", async () => {
    const res = await POST(req({ quantity: 1 }));
    expect(res.status).toBe(400);
  });
});
