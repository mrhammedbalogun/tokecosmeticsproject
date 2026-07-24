import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
const store = new Map<string, string>([["access", "TOK"], ["country", "NG"]]);
vi.mock("next/headers", () => ({ cookies: async () => ({
  get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
  set: (n: string, v: string) => store.set(n, v), delete: (n: string) => store.delete(n),
}) }));
import { POST } from "@/app/api/checkout/route";
const orig = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; store.set("access", "TOK"); store.set("country", "NG"); });
afterEach(() => { global.fetch = orig; vi.restoreAllMocks(); });
function upstream(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
  global.fetch = f as unknown as typeof fetch; return f;
}
const req = (b: unknown) => new Request("http://localhost:3000/api/checkout", {
  method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(b) });

describe("place-order BFF", () => {
  it("attaches an Idempotency-Key and forwards the order body", async () => {
    const f = upstream(201, { order_number: "TC-1", payment: { gateway: "bank_transfer", action: "bank_details", data: {} } });
    const res = await POST(req({ cart_id: "c1", address_id: 1, delivery_option_id: 2, payment_gateway: "bank_transfer" }));
    expect(res.status).toBe(201);
    const [, init] = f.mock.calls[0];
    expect(new Headers((init as RequestInit).headers).get("Idempotency-Key")).toBeTruthy();
  });
  it("401 without a session, no upstream call", async () => {
    store.delete("access"); store.delete("refresh");
    const f = upstream(201, {});
    const res = await POST(req({ cart_id: "c1", address_id: 1, delivery_option_id: 2, payment_gateway: "bank_transfer" }));
    expect(res.status).toBe(401); expect(f).not.toHaveBeenCalled();
  });
  it("passes a CheckoutError status/body straight through", async () => {
    upstream(409, { error: "idempotency_in_progress" });
    const res = await POST(req({ cart_id: "c1", address_id: 1, delivery_option_id: 2, payment_gateway: "bank_transfer" }));
    expect(res.status).toBe(409);
  });
  it("400 when required fields are missing, no upstream call", async () => {
    const f = upstream(201, {});
    const res = await POST(req({ cart_id: "c1" }));
    expect(res.status).toBe(400); expect(f).not.toHaveBeenCalled();
  });
  it("uses a client-supplied idempotency_key as the header and strips it from the upstream body", async () => {
    const f = upstream(201, { order_number: "TC-1", payment: { gateway: "bank_transfer", action: "bank_details", data: {} } });
    const res = await POST(req({
      cart_id: "c1", address_id: 1, delivery_option_id: 2, payment_gateway: "bank_transfer",
      idempotency_key: "fixed-key-123",
    }));
    expect(res.status).toBe(201);
    const [, init] = f.mock.calls[0];
    expect(new Headers((init as RequestInit).headers).get("Idempotency-Key")).toBe("fixed-key-123");
    const sentBody = JSON.parse((init as RequestInit).body as string);
    expect(sentBody.idempotency_key).toBeUndefined();
  });
});
