import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
const store = new Map<string, string>([["access", "TOK"], ["country", "NG"]]);
vi.mock("next/headers", () => ({ cookies: async () => ({
  get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
  set: (n: string, v: string) => store.set(n, v), delete: (n: string) => store.delete(n),
}) }));
import { POST } from "@/app/api/checkout/quote/route";
const orig = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; store.set("access", "TOK"); store.set("country", "NG"); });
afterEach(() => { global.fetch = orig; vi.restoreAllMocks(); });
function upstream(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
  global.fetch = f as unknown as typeof fetch; return f;
}
const req = (b: unknown) => new Request("http://localhost:3000/api/checkout/quote", {
  method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });

describe("quote BFF", () => {
  it("forwards to /checkout/quote/ with Bearer + country and returns totals", async () => {
    const f = upstream(200, { totals: { grand_total: "100.00" }, coupon: { ok: true } });
    const res = await POST(req({ cart_id: "c1", coupon_code: "SAVE" }));
    expect(res.status).toBe(200);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://backend:8000/api/v1/checkout/quote/");
    expect(new Headers((init as RequestInit).headers).get("Authorization")).toBe("Bearer TOK");
  });
  it("401 without a session", async () => {
    store.delete("access"); store.delete("refresh");
    const f = upstream(200, {});
    const res = await POST(req({ cart_id: "c1" }));
    expect(res.status).toBe(401); expect(f).not.toHaveBeenCalled();
  });
});
