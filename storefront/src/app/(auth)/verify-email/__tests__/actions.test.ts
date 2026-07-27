import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const store = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: () => undefined,
    delete: (n: string) => store.delete(n),
  }),
}));

import { verifyEmailAction } from "../actions";

const originalFetch = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; store.clear(); });
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function form(token: string) {
  const fd = new FormData();
  fd.set("token", token);
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

describe("verifyEmailAction", () => {
  it("POSTs the token to the verify endpoint and reports success", async () => {
    const f = upstream(200, { detail: "Email verified.", orders_claimed: 0 });

    const state = await verifyEmailAction({}, form("tok-123"));

    expect(state.verified).toBe(true);
    expect(f.mock.calls[0][0]).toBe("http://backend:8000/api/v1/auth/verify-email/");
    const init = f.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ token: "tok-123" });
  });

  it("surfaces how many past orders were linked, when any were", async () => {
    // A completed verification also claims legacy orders placed with that address, so the
    // page should say so rather than leave the user wondering where they came from.
    upstream(200, { detail: "Email verified.", orders_claimed: 3 });

    const state = await verifyEmailAction({}, form("tok-123"));

    expect(state.ordersClaimed).toBe(3);
  });

  it("treats an expired or reused link as UI, not a crash", async () => {
    // Tokens are single-use and time-limited; clicking an old link is ordinary.
    upstream(400, { detail: "Invalid or expired verification link." });

    const state = await verifyEmailAction({}, form("stale"));

    expect(state.verified).toBe(false);
    expect(state.error).toMatch(/expired/i);
  });

  it("does not echo upstream internals on a 5xx", async () => {
    upstream(500, { detail: "psycopg.OperationalError" });

    const state = await verifyEmailAction({}, form("tok-123"));

    expect(state.verified).toBe(false);
    expect(state.error).not.toMatch(/psycopg/);
  });

  it("refuses an empty token without calling the API", async () => {
    const f = vi.fn();
    global.fetch = f as unknown as typeof fetch;

    const state = await verifyEmailAction({}, form(""));

    expect(state.verified).toBe(false);
    expect(state.error).toBeTruthy();
    expect(f).not.toHaveBeenCalled();
  });

  it("sends no Authorization header — verification must work when signed out", async () => {
    // The link is clicked from an email, quite possibly in a browser with no session.
    store.set("access", "SOME-TOKEN");
    const f = upstream(200, { detail: "Email verified.", orders_claimed: 0 });

    await verifyEmailAction({}, form("tok-123"));

    const init = f.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBeNull();
  });
});
