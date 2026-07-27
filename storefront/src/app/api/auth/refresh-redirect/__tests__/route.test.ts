import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const store = new Map<string, string>();
const setSpy = vi.fn((n: string, v: string) => store.set(n, v));
const deleteSpy = vi.fn((n: string) => store.delete(n));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => setSpy(n, v),
    delete: (n: string) => deleteSpy(n),
  }),
}));

import { GET } from "../route";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.clear();
  setSpy.mockClear();
  deleteSpy.mockClear();
});
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function call(next: string) {
  return GET(new Request(`http://localhost:3000/api/auth/refresh-redirect?next=${next}`));
}

function mockRefresh(status: number, body: unknown) {
  global.fetch = vi.fn(() =>
    Promise.resolve(new Response(JSON.stringify(body), {
      status, headers: { "content-type": "application/json" },
    })),
  ) as unknown as typeof fetch;
}

/**
 * This handler exists because Server Components cannot write cookies (Next 16), so an
 * expired access token can only be renewed by bouncing through a Route Handler. It is
 * the hinge of the whole account gate: if it silently fails, users are logged out; if it
 * blindly obeys `next`, it is an open redirect on an authenticated response.
 */
describe("refresh-redirect", () => {
  it("renews the pair and returns the user to where they were going", async () => {
    store.set("refresh", "OLD-R");
    mockRefresh(200, { access: "NEW-A", refresh: "NEW-R" });

    const res = await call("%2Faccount%2Forders");

    expect(res.headers.get("location")).toBe("http://localhost:3000/account/orders");
    expect(setSpy).toHaveBeenCalledWith("access", "NEW-A");
  });

  it("persists a ROTATED refresh token", async () => {
    // ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION: the old refresh is dead the
    // instant it is used. Not storing the replacement logs the user out on the next hop.
    store.set("refresh", "OLD-R");
    mockRefresh(200, { access: "NEW-A", refresh: "NEW-R" });

    await call("%2Faccount");

    expect(setSpy).toHaveBeenCalledWith("refresh", "NEW-R");
  });

  it("sends a visitor with no refresh cookie to login instead of calling the API", async () => {
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy as unknown as typeof fetch;

    const res = await call("%2Faccount%2Forders");

    expect(res.headers.get("location")).toBe(
      "http://localhost:3000/login?next=%2Faccount%2Forders",
    );
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("clears both cookies and sends to login when the refresh is rejected", async () => {
    // The rotation race: two concurrent requests both refresh, the loser's token is
    // already blacklisted. Leaving a dead refresh cookie in place would loop the user
    // between the gate and this handler forever.
    store.set("refresh", "DEAD-R");
    mockRefresh(401, { detail: "Token is blacklisted" });

    const res = await call("%2Faccount");

    expect(deleteSpy).toHaveBeenCalledWith("refresh");
    expect(deleteSpy).toHaveBeenCalledWith("access");
    expect(res.headers.get("location")).toBe("http://localhost:3000/login?next=%2Faccount");
  });

  it("does NOT destroy the session when the API is merely unreachable", async () => {
    // A bare catch treated every failure as "token dead". So a 502, a timeout, or a
    // deploy blip logged out every user whose access token happened to be stale during
    // it — throwing away a valid 14-day refresh token over a transient error.
    // The loop stays impossible: the next attempt either succeeds or 401s properly.
    store.set("refresh", "STILL-GOOD-R");
    mockRefresh(502, { detail: "Bad gateway" });

    const res = await call("%2Faccount");

    expect(deleteSpy).not.toHaveBeenCalled();
    expect(res.headers.get("location")).toBe("http://localhost:3000/login?next=%2Faccount");
  });

  it("does NOT destroy the session when the refresh call throws outright", async () => {
    // Network-level failure (DNS, connection refused) — not an ApiError at all.
    store.set("refresh", "STILL-GOOD-R");
    global.fetch = vi.fn(() => Promise.reject(new Error("ECONNREFUSED"))) as unknown as typeof fetch;

    const res = await call("%2Faccount");

    expect(deleteSpy).not.toHaveBeenCalled();
    expect(res.headers.get("location")).toBe("http://localhost:3000/login?next=%2Faccount");
  });

  it("DOES clear on a 400, which is how SimpleJWT reports a spent token", async () => {
    store.set("refresh", "DEAD-R");
    mockRefresh(400, { detail: "Token is invalid or expired" });

    await call("%2Faccount");

    expect(deleteSpy).toHaveBeenCalledWith("refresh");
    expect(deleteSpy).toHaveBeenCalledWith("access");
  });

  it("refuses to redirect off-site even after a successful refresh", async () => {
    store.set("refresh", "OLD-R");
    mockRefresh(200, { access: "NEW-A", refresh: "NEW-R" });

    const res = await call("https%3A%2F%2Fevil.example");

    expect(res.headers.get("location")).toBe("http://localhost:3000/account");
  });
});
