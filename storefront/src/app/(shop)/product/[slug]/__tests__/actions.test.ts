import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const store = new Map<string, string>();
const setSpy = vi.fn((n: string, v: string) => store.set(n, v));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => setSpy(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

import { submitReviewAction } from "../actions";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.clear();
  store.set("access", "AAA"); // signed-in session
  store.set("refresh", "RRR");
  setSpy.mockClear();
});
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function form(fields: Record<string, string>) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.set(k, v);
  return fd;
}

function upstream(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status, headers: { "content-type": "application/json" },
    }),
  );
  global.fetch = f as unknown as typeof fetch;
  return f;
}

describe("submitReviewAction", () => {
  it("POSTs the review to /products/<slug>/reviews/ with the session token", async () => {
    const f = upstream(201, { rating: 5 });

    const state = await submitReviewAction({}, form({
      slug: "shea-butter", rating: "5", title: "Love it", body: "Great product",
    }));

    expect(state.submitted).toBe(true);
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain("/products/shea-butter/reviews/");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer AAA");
    expect(JSON.parse(String(init.body))).toEqual({
      rating: 5, title: "Love it", body: "Great product",
    });
  });

  it("requires a star rating without calling the API", async () => {
    const f = vi.fn();
    global.fetch = f as unknown as typeof fetch;
    const state = await submitReviewAction({}, form({ slug: "s", body: "text" }));
    expect(state.submitted).toBeUndefined();
    expect(state.error).toMatch(/rating/i);
    expect(f).not.toHaveBeenCalled();
  });

  it("requires a body without calling the API", async () => {
    const f = vi.fn();
    global.fetch = f as unknown as typeof fetch;
    const state = await submitReviewAction({}, form({ slug: "s", rating: "4", body: "  " }));
    expect(state.error).toBeTruthy();
    expect(f).not.toHaveBeenCalled();
  });

  it("surfaces the verified-purchaser 403 detail verbatim", async () => {
    upstream(403, { detail: "Only verified purchasers can review this product." });
    const state = await submitReviewAction({}, form({
      slug: "shea-butter", rating: "5", body: "never bought it",
    }));
    expect(state.error).toBe("Only verified purchasers can review this product.");
  });

  it("surfaces the already-reviewed 400 detail verbatim", async () => {
    upstream(400, { detail: "You have already reviewed this product." });
    const state = await submitReviewAction({}, form({
      slug: "shea-butter", rating: "5", body: "again",
    }));
    expect(state.error).toBe("You have already reviewed this product.");
  });

  it("maps a dead session (401 even after refresh) to a sign-in message", async () => {
    upstream(401, { detail: "Token is invalid or expired" });
    const state = await submitReviewAction({}, form({
      slug: "shea-butter", rating: "5", body: "text",
    }));
    expect(state.error).toMatch(/sign in/i);
  });
});
