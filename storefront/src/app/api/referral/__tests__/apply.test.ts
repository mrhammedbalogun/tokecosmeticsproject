import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>([["access", "TOK"]]);
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

import { POST } from "@/app/api/referral/route";

const orig = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.set("access", "TOK");
});
afterEach(() => { global.fetch = orig; vi.restoreAllMocks(); });

function upstream(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), {
    status, headers: { "content-type": "application/json" },
  }));
  global.fetch = f as unknown as typeof fetch;
  return f;
}

const req = (body: unknown) => new Request("http://localhost:3000/api/referral", {
  method: "POST", headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

describe("apply-a-referral-code BFF", () => {
  it("sets the httpOnly attribution cookie when the code is valid", async () => {
    // The whole point of routing manual entry through the server: the browser asks, the
    // server decides, and the cookie the checkout reads is written here — never by JS.
    upstream(200, { valid: true, referrer_name: "Amina" });
    const res = await POST(req({ code: "amina7k3p" }));

    expect(await res.json()).toEqual({ valid: true, referrer_name: "Amina" });
    const cookie = res.headers.get("set-cookie") ?? "";
    expect(cookie).toContain("tc_ref=AMINA7K3P");
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("SameSite=Lax");
    expect(cookie).toContain("Max-Age=2592000"); // 30 days, matching the proxy
  });

  it("writes NO cookie when the code is not valid", async () => {
    // A wrong code must not wipe attribution the visitor already earned by clicking a
    // real link.
    upstream(200, { valid: false, reason: "not_found" });
    const res = await POST(req({ code: "NOSUCHCODE" }));

    expect(res.headers.get("set-cookie")).toBeNull();
    expect((await res.json()).reason).toBe("not_found");
  });

  it("rejects a malformed code without calling upstream at all", async () => {
    const f = upstream(200, { valid: true });
    const res = await POST(req({ code: "<script>alert(1)</script>" }));

    expect(f).not.toHaveBeenCalled();
    expect((await res.json()).valid).toBe(false);
    expect(res.headers.get("set-cookie")).toBeNull();
  });

  it("forwards the session so the backend can spot a self-referral", async () => {
    const f = upstream(200, { valid: false, reason: "self" });
    await POST(req({ code: "AMINA7K3P" }));

    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://backend:8000/api/v1/referrals/lookup/?code=AMINA7K3P");
    expect(new Headers((init as RequestInit).headers).get("Authorization")).toBe("Bearer TOK");
  });

  it("still answers when there is no session at all", async () => {
    // The cart works for logged-out visitors, so this route has to as well.
    store.delete("access");
    const f = upstream(200, { valid: true, referrer_name: "Amina" });
    const res = await POST(req({ code: "AMINA7K3P" }));

    expect(res.status).toBe(200);
    expect(new Headers((f.mock.calls[0][1] as RequestInit).headers).get("Authorization")).toBeNull();
    expect(res.headers.get("set-cookie")).toContain("tc_ref=AMINA7K3P");
  });

  it("degrades to a plain message when the lookup is throttled", async () => {
    upstream(429, { detail: "Request was throttled." });
    const res = await POST(req({ code: "AMINA7K3P" }));

    expect(res.status).toBe(200); // never surfaces a raw 429 into the cart UI
    expect((await res.json()).reason).toBe("rate_limited");
    expect(res.headers.get("set-cookie")).toBeNull();
  });
});
