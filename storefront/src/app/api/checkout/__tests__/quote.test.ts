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
  it("sends the referral code from the COOKIE, and IGNORES one supplied in the body", async () => {
    // The place-order twin of this is pinned in place.test.ts, and for a stronger reason
    // (it decides who is paid). Here the stake is agreement: since 2026-08-27 an
    // attributed order discounts the customer's own goods, so if the preview could read a
    // different code from the placement, the two would compute different totals and the
    // `expected_total` guard would refuse the order at the last click.
    store.set("tc_ref", "AMINA7K3P");
    const f = upstream(200, { totals: { grand_total: "95.00" }, coupon: { ok: true } });
    await POST(req({ cart_id: "c1", referral_code: "SOMEONEELSE" }));
    const body = JSON.parse((f.mock.calls[0][1] as RequestInit).body as string);
    expect(body.referral_code).toBe("AMINA7K3P");
    store.delete("tc_ref");
  });

  it("sends an empty referral code when there is no cookie", async () => {
    store.delete("tc_ref");
    const f = upstream(200, { totals: { grand_total: "100.00" }, coupon: { ok: true } });
    await POST(req({ cart_id: "c1" }));
    expect(JSON.parse((f.mock.calls[0][1] as RequestInit).body as string).referral_code).toBe("");
  });

  it("drops a malformed cookie rather than forwarding it", async () => {
    // `normalizeReferralCode` rejects anything outside [A-Z2-9]{5,32}. A cookie that
    // failed that check is not a code, and forwarding it would put an arbitrary
    // attacker-chosen string into the quote payload for no gain.
    store.set("tc_ref", "not a code!");
    const f = upstream(200, { totals: { grand_total: "100.00" }, coupon: { ok: true } });
    await POST(req({ cart_id: "c1" }));
    expect(JSON.parse((f.mock.calls[0][1] as RequestInit).body as string).referral_code).toBe("");
    store.delete("tc_ref");
  });

  it("routes a session-less request to the guest quote twin, anonymously (Plan-38)", async () => {
    store.delete("access"); store.delete("refresh");
    const f = upstream(200, { totals: { grand_total: "100.00" }, coupon: { ok: true } });
    const res = await POST(req({
      cart_id: "c1", address: { line1: "1 Guest Close", country_code: "NG" },
      guest_email: "g@example.com", delivery_option_id: 2,
    }));
    expect(res.status).toBe(200);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://backend:8000/api/v1/checkout/guest/quote/");
    expect(new Headers((init as RequestInit).headers).get("Authorization")).toBeNull();
    expect(JSON.parse((init as RequestInit).body as string).guest_email).toBe("g@example.com");
  });
});
