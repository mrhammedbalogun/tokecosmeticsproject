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

class Redirected extends Error {
  constructor(public to: string) { super(`NEXT_REDIRECT ${to}`); }
}
vi.mock("next/navigation", () => ({
  redirect: (to: string) => { throw new Redirected(to); },
}));

import { loginAction } from "../actions";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.clear();
  setSpy.mockClear();
});
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function form(fields: Record<string, string>) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.set(k, v);
  return fd;
}

function upstream(status: number, body: unknown) {
  global.fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status, headers: { "content-type": "application/json" },
    }),
  ) as unknown as typeof fetch;
}

describe("loginAction", () => {
  it("signs the user in and redirects to the requested destination", async () => {
    upstream(200, { access: "AAA", refresh: "RRR" });

    await expect(
      loginAction({}, form({ email: "a@b.com", password: "pw", next: "/account/orders" })),
    ).rejects.toThrow("NEXT_REDIRECT /account/orders");

    expect(setSpy).toHaveBeenCalledWith("access", "AAA");
    expect(setSpy).toHaveBeenCalledWith("refresh", "RRR");
  });

  it("forwards the Turnstile token to the backend as turnstile_token", async () => {
    upstream(200, { access: "AAA", refresh: "RRR" });

    await expect(
      loginAction({}, form({
        email: "a@b.com", password: "pw", "cf-turnstile-response": "tok-123",
      })),
    ).rejects.toThrow("NEXT_REDIRECT /account");

    const [, init] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(JSON.parse(init.body)).toMatchObject({ turnstile_token: "tok-123" });
  });

  it("omits turnstile_token entirely when the widget did not run", async () => {
    // Gate-off deployments must keep sending exactly the old body shape.
    upstream(200, { access: "AAA", refresh: "RRR" });

    await expect(
      loginAction({}, form({ email: "a@b.com", password: "pw" })),
    ).rejects.toThrow("NEXT_REDIRECT /account");

    const [, init] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(JSON.parse(init.body)).not.toHaveProperty("turnstile_token");
  });

  it("re-validates `next` server-side — the hidden field is client-supplied", async () => {
    // The action is a public POST endpoint; the hidden input is not a trust boundary.
    upstream(200, { access: "AAA", refresh: "RRR" });

    await expect(
      loginAction({}, form({ email: "a@b.com", password: "pw", next: "https://evil.example/pwn" })),
    ).rejects.toThrow("NEXT_REDIRECT /account");
  });

  it("rejects a protocol-relative destination too", async () => {
    upstream(200, { access: "AAA", refresh: "RRR" });

    await expect(
      loginAction({}, form({ email: "a@b.com", password: "pw", next: "//evil.example" })),
    ).rejects.toThrow("NEXT_REDIRECT /account");
  });

  it("falls back to the default destination when `next` is absent", async () => {
    upstream(200, { access: "AAA", refresh: "RRR" });

    await expect(
      loginAction({}, form({ email: "a@b.com", password: "pw" })),
    ).rejects.toThrow("NEXT_REDIRECT /account");
  });

  it("returns one generic message on a rejected credential and sets no cookies", async () => {
    upstream(401, { detail: "No active account found with the given credentials" });

    const state = await loginAction({}, form({ email: "a@b.com", password: "bad", next: "/account" }));

    expect(state.error).toBe("Email or password is incorrect.");
    expect(setSpy).not.toHaveBeenCalled();
  });

  it("keeps the submitted email so the user does not retype it after a failure", async () => {
    upstream(401, { detail: "nope" });

    const state = await loginAction({}, form({ email: "a@b.com", password: "bad" }));

    expect(state.email).toBe("a@b.com");
  });

  it("preserves `next` across a failed attempt", async () => {
    upstream(401, { detail: "nope" });

    const state = await loginAction({}, form({ email: "a@b.com", password: "bad", next: "/account/orders" }));

    expect(state.next).toBe("/account/orders");
  });

  it("sanitises `next` in the returned state as well, not only on the redirect", async () => {
    // Otherwise a failed attempt re-renders the form with a hostile hidden value that the
    // NEXT submit would carry — sanitising only the success path just delays the problem.
    upstream(401, { detail: "nope" });

    const state = await loginAction({}, form({ email: "a@b.com", password: "bad", next: "//evil.example" }));

    expect(state.next).toBe("/account");
  });

  it("validates missing input without calling the API", async () => {
    const f = vi.fn();
    global.fetch = f as unknown as typeof fetch;

    const state = await loginAction({}, form({ email: "", password: "" }));

    expect(state.error).toBeTruthy();
    expect(f).not.toHaveBeenCalled();
  });

  it("reports a throttled attempt as such", async () => {
    upstream(429, { detail: "Request was throttled." });

    const state = await loginAction({}, form({ email: "a@b.com", password: "pw" }));

    expect(state.error).toMatch(/too many/i);
  });

  it("does not forward X-Forwarded-For — it would look like a rate-limit fix and is not one", async () => {
    // NUM_PROXIES is unset, so DRF keys the throttle on the WHOLE XFF chain; forwarding a
    // client-controlled prefix cannot be made correct by any NUM_PROXIES value (the
    // direct-to-API and via-BFF paths need different ones). The real fix is an
    // email-keyed scoped throttle on the backend. Tracked as its own slice.
    const f = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ access: "AAA", refresh: "RRR" }), {
        status: 200, headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = f as unknown as typeof fetch;

    await expect(
      loginAction({}, form({ email: "a@b.com", password: "pw" })),
    ).rejects.toThrow(/NEXT_REDIRECT/);

    const headers = new Headers((f.mock.calls[0][1] as RequestInit).headers);
    expect(headers.get("X-Forwarded-For")).toBeNull();
  });
});
