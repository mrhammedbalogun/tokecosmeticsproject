import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>([["access", "OLD"], ["refresh", "RRR"]]);
const setSpy = vi.fn((n: string, v: string) => store.set(n, v));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => setSpy(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

import { fetchWithAuth } from "@/lib/session";

const originalFetch = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; setSpy.mockClear(); store.set("access", "OLD"); });
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

describe("fetchWithAuth silent refresh", () => {
  it("refreshes once on a 401, stores the new access token, and retries", async () => {
    const calls: string[] = [];
    global.fetch = vi.fn((url: string, init?: RequestInit) => {
      calls.push(url);
      if (url.endsWith("/auth/me/") && new Headers(init?.headers).get("Authorization") === "Bearer OLD")
        return Promise.resolve(new Response("{}", { status: 401 }));
      if (url.endsWith("/auth/token/refresh/"))
        return Promise.resolve(new Response(JSON.stringify({ access: "NEW" }), { status: 200, headers: { "content-type": "application/json" } }));
      return Promise.resolve(new Response(JSON.stringify({ email: "a@b.com" }), { status: 200, headers: { "content-type": "application/json" } }));
    }) as unknown as typeof fetch;

    const data = await fetchWithAuth<{ email: string }>("/auth/me/");
    expect(data.email).toBe("a@b.com");
    expect(setSpy).toHaveBeenCalledWith("access", "NEW");
    expect(calls.some((u) => u.endsWith("/auth/token/refresh/"))).toBe(true);
  });
});
