import { describe, it, expect, vi, afterEach } from "vitest";
import { verifyPayment } from "@/lib/payment-verify";

const orig = global.fetch;
afterEach(() => { global.fetch = orig; vi.restoreAllMocks(); });

function mock(status: number, body: unknown) {
  global.fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } })
  ) as unknown as typeof fetch;
}

describe("verifyPayment", () => {
  it("maps a succeeded verify to ok + order details", async () => {
    mock(200, { order_number: "TC-9", order_status: "processing", payment_status: "succeeded" });
    const out = await verifyPayment("TC-ref-9");
    expect(out).toEqual({ ok: true, orderNumber: "TC-9", orderStatus: "processing", paymentStatus: "succeeded" });
  });
  it("returns ok:false on a non-2xx", async () => {
    mock(404, { detail: "Not found." });
    const out = await verifyPayment("nope");
    expect(out.ok).toBe(false);
  });
  it("returns ok:false on a network throw", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("boom")) as unknown as typeof fetch;
    const out = await verifyPayment("x");
    expect(out.ok).toBe(false);
  });
});
