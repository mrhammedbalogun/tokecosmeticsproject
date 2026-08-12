import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

class Redirected extends Error {
  constructor(public to: string) {
    super(`NEXT_REDIRECT ${to}`);
  }
}
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Redirected(to);
  },
}));

import { loginAction, type LoginState } from "../actions";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.clear();
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

function form(fields: Record<string, string>): FormData {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.set(k, v);
  return fd;
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function redirectFrom(fn: () => Promise<unknown>): Promise<string> {
  try {
    await fn();
  } catch (e) {
    if (e instanceof Redirected) return e.to;
    throw e;
  }
  throw new Error("expected a redirect");
}

const EMPTY: LoginState = {};

describe("step one of the ceremony", () => {
  it("stores a preauth token and sends an enrolled staff member to the code prompt", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse({ preauth_token: "PRE", expires_in: 600, totp_enrolled: true })),
    ) as unknown as typeof fetch;

    const to = await redirectFrom(() =>
      loginAction(EMPTY, form({ email: "a@b.com", password: "pw", next: "/orders" })),
    );

    expect(to).toBe(`/totp?next=${encodeURIComponent("/orders")}&method=totp`);
    expect(store.get("admin_preauth")).toBe("PRE");
    // No session anywhere. `/auth/admin-token/` mints nothing, and this action cannot
    // invent one.
    expect(store.has("admin_access")).toBe(false);
  });

  it("sends an UNenrolled staff member to the same page with a setup hint", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse({ preauth_token: "PRE", expires_in: 600, totp_enrolled: false })),
    ) as unknown as typeof fetch;

    const to = await redirectFrom(() =>
      loginAction(EMPTY, form({ email: "a@b.com", password: "pw" })),
    );

    expect(to).toBe(`/totp?next=${encodeURIComponent("/")}&setup=1`);
    expect(store.get("admin_preauth")).toBe("PRE");
  });

  it("sends an email-method staff member to the email code screen", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(
        jsonResponse({ preauth_token: "PRE", expires_in: 600, second_factor: "email" }),
      ),
    ) as unknown as typeof fetch;

    const to = await redirectFrom(() =>
      loginAction(EMPTY, form({ email: "a@b.com", password: "pw" })),
    );
    expect(to).toBe(`/totp?next=${encodeURIComponent("/")}&method=email`);
  });

  it("redeems a trusted device at the confirm endpoint and skips the code screen", async () => {
    store.set("admin_device", "DEV");
    const calls: Array<{ url: string; body: unknown }> = [];
    global.fetch = vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, body: JSON.parse(String(init?.body)) });
      if (url.includes("/auth/admin-token/")) {
        return Promise.resolve(
          jsonResponse({
            preauth_token: "PRE",
            expires_in: 600,
            second_factor: "totp",
            device_trusted: true,
          }),
        );
      }
      return Promise.resolve(jsonResponse({ access: "A", refresh: "R" }));
    }) as unknown as typeof fetch;

    const to = await redirectFrom(() =>
      loginAction(EMPTY, form({ email: "a@b.com", password: "pw", next: "/orders" })),
    );

    // Straight to the destination — but THROUGH the confirm endpoint, never around it.
    expect(to).toBe("/orders");
    expect(calls[1].url).toContain("/auth/admin-totp/confirm/");
    expect(calls[1].body).toEqual({ method: "trusted_device", device_token: "DEV" });
    expect(store.get("admin_access")).toBe("A");
    expect(store.has("admin_preauth")).toBe(false);
  });

  it("falls back to the code prompt when the trusted device is refused, dropping the dead cookie", async () => {
    store.set("admin_device", "DEV");
    global.fetch = vi.fn((url: string) => {
      if (url.includes("/auth/admin-token/")) {
        return Promise.resolve(
          jsonResponse({
            preauth_token: "PRE",
            expires_in: 600,
            second_factor: "totp",
            device_trusted: true,
          }),
        );
      }
      return Promise.resolve(jsonResponse({ detail: "nope" }, 401));
    }) as unknown as typeof fetch;

    const to = await redirectFrom(() =>
      loginAction(EMPTY, form({ email: "a@b.com", password: "pw" })),
    );

    expect(to).toBe(`/totp?next=${encodeURIComponent("/")}&method=totp`);
    expect(store.has("admin_device")).toBe(false);
    expect(store.get("admin_preauth")).toBe("PRE");
  });

  it("forwards the Turnstile token from the hidden widget field", async () => {
    let body = "";
    global.fetch = vi.fn((_u: string, init?: RequestInit) => {
      body = String(init?.body);
      return Promise.resolve(jsonResponse({ preauth_token: "PRE", expires_in: 600 }));
    }) as unknown as typeof fetch;

    await redirectFrom(() =>
      loginAction(
        EMPTY,
        form({ email: "a@b.com", password: "pw", "cf-turnstile-response": "TT" }),
      ),
    );
    expect(JSON.parse(body)).toMatchObject({ turnstile_token: "TT" });
  });

  it("returns ONE message for a wrong password, a non-staff account and an unknown address", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse({ detail: "No active account found" }, 401)),
    ) as unknown as typeof fetch;

    const state = await loginAction(EMPTY, form({ email: "a@b.com", password: "bad" }));
    expect(state.error).toBe("Email or password is incorrect.");
    // The address is echoed so the form does not make them retype it; the password is not.
    expect(state.email).toBe("a@b.com");
    expect(store.size).toBe(0);
  });

  it("surfaces a Turnstile refusal as itself, not as a password error", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse({ detail: "Human verification failed. Try again." }, 403)),
    ) as unknown as typeof fetch;

    const state = await loginAction(EMPTY, form({ email: "a@b.com", password: "pw" }));
    expect(state.error).toMatch(/verification/i);
  });

  it("says so plainly when the staff gate throttles", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse({ detail: "Request was throttled." }, 429)),
    ) as unknown as typeof fetch;

    const state = await loginAction(EMPTY, form({ email: "a@b.com", password: "pw" }));
    expect(state.error).toMatch(/too many/i);
  });

  it("sanitises a hostile ?next= before it reaches either the redirect or the re-rendered form", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse({ detail: "nope" }, 401)),
    ) as unknown as typeof fetch;

    const state = await loginAction(
      EMPTY,
      form({ email: "a@b.com", password: "bad", next: "//evil.example/x" }),
    );
    expect(state.next).toBe("/");
  });

  it("refuses an empty submission without calling the API", async () => {
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy as unknown as typeof fetch;
    const state = await loginAction(EMPTY, form({ email: "", password: "" }));
    expect(state.error).toMatch(/enter your email/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
