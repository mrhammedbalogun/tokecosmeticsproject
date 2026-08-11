import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
const store = new Map<string, string>([["access", "TOK"], ["country", "NG"]]);
vi.mock("next/headers", () => ({ cookies: async () => ({
  get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
  set: (n: string, v: string) => store.set(n, v), delete: (n: string) => store.delete(n),
}) }));
import { GET } from "@/app/api/checkout/gig-centres/route";
const orig = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; store.set("access", "TOK"); store.set("country", "NG"); });
afterEach(() => { global.fetch = orig; vi.restoreAllMocks(); });
function upstream(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
  global.fetch = f as unknown as typeof fetch; return f;
}
const req = (qs: string) => new Request(`http://localhost:3000/api/checkout/gig-centres?${qs}`);

describe("gig-centres BFF (32b slice 4)", () => {
  it("forwards address_id to /checkout/gig-centres/ with Bearer + country", async () => {
    const f = upstream(200, [{ id: 101, name: "GIG Oregun", address: "52 Oregun Rd", distance_km: 2.4 }]);
    const res = await GET(req("address_id=7"));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual([{ id: 101, name: "GIG Oregun", address: "52 Oregun Rd", distance_km: 2.4 }]);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://backend:8000/api/v1/checkout/gig-centres/?address_id=7");
    expect(new Headers((init as RequestInit).headers).get("Authorization")).toBe("Bearer TOK");
    expect(new Headers((init as RequestInit).headers).get("X-Country")).toBe("NG");
  });

  it("401 without a session, no upstream call", async () => {
    store.delete("access"); store.delete("refresh");
    const f = upstream(200, []);
    expect((await GET(req("address_id=7"))).status).toBe(401);
    expect(f).not.toHaveBeenCalled();
  });

  it("400 when address_id is missing, no upstream call", async () => {
    const f = upstream(200, []);
    expect((await GET(req(""))).status).toBe(400);
    expect(f).not.toHaveBeenCalled();
  });

  it("passes through upstream error status + body", async () => {
    upstream(404, { detail: "Not found." });
    const res = await GET(req("address_id=999"));
    expect(res.status).toBe(404);
  });
});
