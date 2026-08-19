import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
const store = new Map<string, string>([["access", "TOK"], ["country", "NG"]]);
vi.mock("next/headers", () => ({ cookies: async () => ({
  get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
  set: (n: string, v: string) => store.set(n, v), delete: (n: string) => store.delete(n),
}) }));
import { POST } from "@/app/api/checkout/verify/route";
const orig = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; store.set("access", "TOK"); store.set("country", "NG"); });
afterEach(() => { global.fetch = orig; vi.restoreAllMocks(); });
function upstream(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
  global.fetch = f as unknown as typeof fetch; return f;
}
const req = (b: unknown) => new Request("http://localhost:3000/api/checkout/verify", {
  method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });

describe("verify BFF", () => {
  it("forwards {reference} to the verify endpoint and returns the status body", async () => {
    const f = upstream(200, { order_number: "TC-1", order_status: "processing", payment_status: "succeeded" });
    const res = await POST(req({ reference: "TC-ref-1" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ order_number: "TC-1", payment_status: "succeeded" });
    const [url] = f.mock.calls[0];
    expect(String(url)).toContain("/payments/TC-ref-1/verify/");
  });
  it("401 without a session OR guest cookie, no upstream call", async () => {
    store.delete("access"); store.delete("refresh"); store.delete("guest_order");
    const f = upstream(200, {});
    const res = await POST(req({ reference: "TC-ref-1" }));
    expect(res.status).toBe(401); expect(f).not.toHaveBeenCalled();
  });
  it("guest verify forwards the httpOnly cookie's token in the body (Plan-38)", async () => {
    store.delete("access"); store.delete("refresh");
    store.set("guest_order", "signed-token");
    const f = upstream(200, { order_number: "TC-9", order_status: "pending_payment", payment_status: "initiated" });
    const res = await POST(req({ reference: "TC-ref-9" }));
    expect(res.status).toBe(200);
    const [, init] = f.mock.calls[0];
    expect(new Headers((init as RequestInit).headers).get("Authorization")).toBeNull();
    expect(JSON.parse((init as RequestInit).body as string).guest_token).toBe("signed-token");
  });
  it("an authed session wins over a stale guest cookie — no token in the body", async () => {
    store.set("guest_order", "stale-token");
    const f = upstream(200, { order_number: "TC-1", order_status: "processing", payment_status: "succeeded" });
    const res = await POST(req({ reference: "TC-ref-1" }));
    expect(res.status).toBe(200);
    const [, init] = f.mock.calls[0];
    expect(JSON.parse((init as RequestInit).body as string).guest_token).toBeUndefined();
    store.delete("guest_order");
  });
  it("400 when reference is missing, no upstream call", async () => {
    const f = upstream(200, {});
    const res = await POST(req({}));
    expect(res.status).toBe(400); expect(f).not.toHaveBeenCalled();
  });
  it("passes an upstream 404 straight through (order not the user's)", async () => {
    upstream(404, { detail: "Not found." });
    const res = await POST(req({ reference: "TC-ref-1" }));
    expect(res.status).toBe(404);
  });
});
