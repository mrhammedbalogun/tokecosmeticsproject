import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>([["country", "GB"]]);
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

import { GET } from "@/app/api/search/suggest/route";

const originalFetch = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; store.set("country", "GB"); });
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function upstream(body: unknown) {
  const f = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), {
    status: 200, headers: { "content-type": "application/json" },
  }));
  global.fetch = f as unknown as typeof fetch;
  return f;
}

describe("suggest BFF", () => {
  it("forwards q, the country cookie, and the caller IP", async () => {
    const f = upstream([{ name: "Radiance Glow Serum", slug: "radiance-glow-serum" }]);
    const res = await GET(new Request("http://localhost:3000/api/search/suggest?q=rad", {
      headers: { "x-forwarded-for": "203.0.113.9" },
    }));
    expect(res.status).toBe(200);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://backend:8000/api/v1/search/suggest/?q=rad");
    const h = new Headers((init as RequestInit).headers);
    expect(h.get("X-Country")).toBe("GB");
    expect(h.get("X-Forwarded-For")).toBe("203.0.113.9");
    expect(await res.json()).toEqual([{ name: "Radiance Glow Serum", slug: "radiance-glow-serum" }]);
  });

  it("short-circuits an empty q without an upstream call", async () => {
    const f = upstream([]);
    const res = await GET(new Request("http://localhost:3000/api/search/suggest?q="));
    expect(await res.json()).toEqual([]);
    expect(f).not.toHaveBeenCalled();
  });
});
