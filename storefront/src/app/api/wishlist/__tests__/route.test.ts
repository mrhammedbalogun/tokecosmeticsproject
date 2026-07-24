import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>([["access", "TOK"]]);
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

import { GET, POST, DELETE } from "@/app/api/wishlist/[[...sku]]/route";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.set("access", "TOK");
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

function upstream(status: number, body: unknown) {
  // 204/205/304 are "null body status" codes: undici's Response constructor throws
  // if a body is passed with them, so send null for those (mirrors the auth route test).
  const nullBody = status === 204 || status === 205 || status === 304;
  const f = vi.fn().mockResolvedValue(
    new Response(nullBody ? null : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
  global.fetch = f as unknown as typeof fetch;
  return f;
}
const ctx = (sku?: string) => ({ params: Promise.resolve({ sku: sku ? [sku] : undefined }) });

describe("wishlist BFF", () => {
  it("POST forwards {sku} with the Bearer token", async () => {
    const f = upstream(201, { sku: "TOKE-X" });
    const res = await POST(
      new Request("http://localhost:3000/api/wishlist", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ sku: "TOKE-X" }),
      }),
      ctx(),
    );
    expect(res.status).toBe(201);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://backend:8000/api/v1/me/wishlist/");
    expect(new Headers((init as RequestInit).headers).get("Authorization")).toBe("Bearer TOK");
  });

  it("DELETE targets the sku path", async () => {
    const f = upstream(204, null);
    const res = await DELETE(
      new Request("http://localhost:3000/api/wishlist/TOKE-X", {
        method: "DELETE",
      }),
      ctx("TOKE-X"),
    );
    expect(res.status).toBe(204);
    expect(f.mock.calls[0][0]).toBe("http://backend:8000/api/v1/me/wishlist/TOKE-X/");
  });

  it("returns 401 without a session (no upstream call)", async () => {
    store.delete("access");
    const f = upstream(200, {});
    const res = await GET(new Request("http://localhost:3000/api/wishlist"), ctx());
    expect(res.status).toBe(401);
    expect(f).not.toHaveBeenCalled();
  });
});
