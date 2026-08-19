import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
const store = new Map<string, string>([
  ["access", "TOK"],
  ["country", "NG"],
]);
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));
import { POST } from "@/app/api/checkout/pay/route";

const orig = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.set("access", "TOK");
  store.set("country", "NG");
});
afterEach(() => {
  global.fetch = orig;
  vi.restoreAllMocks();
});

function upstream(status: number, body: unknown) {
  const f = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } })
    );
  global.fetch = f as unknown as typeof fetch;
  return f;
}
const req = (b: unknown) =>
  new Request("http://localhost:3000/api/checkout/pay", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(b),
  });

const OK = {
  order_number: "TC-300",
  payment: { gateway: "paystack", action: "redirect", reference: "TC-ref-9", data: { access_code: "ac_9" } },
};

describe("re-pay BFF", () => {
  it("posts the chosen gateway to the order's pay endpoint and returns the envelope", async () => {
    const f = upstream(200, OK);
    const res = await POST(req({ order_number: "TC-300", payment_gateway: "paystack" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ order_number: "TC-300" });
    const [url, init] = f.mock.calls[0];
    expect(String(url)).toContain("/orders/TC-300/pay/");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ payment_gateway: "paystack" });
  });

  it("always sends an Idempotency-Key", async () => {
    const f = upstream(200, OK);
    await POST(req({ order_number: "TC-300", payment_gateway: "paystack" }));
    const [, init] = f.mock.calls[0];
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.get("Idempotency-Key")).toBeTruthy();
  });

  it("prefers a client-supplied key so a lost response resumes the same attempt", async () => {
    const f = upstream(200, OK);
    await POST(req({ order_number: "TC-300", payment_gateway: "paystack", idempotency_key: "mine-1" }));
    const [, init] = f.mock.calls[0];
    expect(new Headers((init as RequestInit).headers).get("Idempotency-Key")).toBe("mine-1");
    // The key is a header concern — it must never be forwarded in the body.
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ payment_gateway: "paystack" });
  });

  it("401 without a session OR guest cookie, no upstream call", async () => {
    store.delete("access");
    store.delete("refresh");
    store.delete("guest_order");
    const f = upstream(200, OK);
    const res = await POST(req({ order_number: "TC-300", payment_gateway: "paystack" }));
    expect(res.status).toBe(401);
    expect(f).not.toHaveBeenCalled();
  });

  it("guest re-pay forwards the httpOnly cookie's token in the body (Plan-38)", async () => {
    store.delete("access");
    store.delete("refresh");
    store.set("guest_order", "signed-token");
    const f = upstream(200, OK);
    const res = await POST(req({ order_number: "TC-300", payment_gateway: "paystack" }));
    expect(res.status).toBe(200);
    const [, init] = f.mock.calls[0];
    expect(new Headers((init as RequestInit).headers).get("Authorization")).toBeNull();
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      payment_gateway: "paystack",
      guest_token: "signed-token",
    });
    store.delete("guest_order");
  });

  it("an authed session wins over a stale guest cookie — no token in the body", async () => {
    store.set("guest_order", "stale-token");
    const f = upstream(200, OK);
    await POST(req({ order_number: "TC-300", payment_gateway: "paystack" }));
    const [, init] = f.mock.calls[0];
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ payment_gateway: "paystack" });
    store.delete("guest_order");
  });

  it("400 when the order number or gateway is missing, no upstream call", async () => {
    const f = upstream(200, OK);
    expect((await POST(req({ payment_gateway: "paystack" }))).status).toBe(400);
    expect((await POST(req({ order_number: "TC-300" }))).status).toBe(400);
    expect(f).not.toHaveBeenCalled();
  });

  it("passes an upstream 409 straight through (order no longer payable)", async () => {
    upstream(409, { error: "order_not_payable" });
    const res = await POST(req({ order_number: "TC-300", payment_gateway: "paystack" }));
    expect(res.status).toBe(409);
    expect(await res.json()).toMatchObject({ error: "order_not_payable" });
  });

  it("encodes the order number into the path", async () => {
    const f = upstream(200, OK);
    await POST(req({ order_number: "TC/300 X", payment_gateway: "paystack" }));
    expect(String(f.mock.calls[0][0])).toContain("/orders/TC%2F300%20X/pay/");
  });
});
