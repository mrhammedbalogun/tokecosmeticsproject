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

import { registerAction } from "../actions";

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

const VALID = { email: "a@b.com", password: "Str0ng-Passw0rd-9x", first_name: "Ada" };

function upstreamOk() {
  const f = vi.fn((url: string, _init?: RequestInit) => {
    const body = String(url).endsWith("/auth/token/")
      ? { access: "AAA", refresh: "RRR" }
      : {};
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200, headers: { "content-type": "application/json" },
    }));
  });
  global.fetch = f as unknown as typeof fetch;
  return f;
}

function upstreamFail(status: number, body: unknown) {
  global.fetch = vi.fn((url: string) => {
    if (String(url).endsWith("/auth/register/")) {
      return Promise.resolve(new Response(JSON.stringify(body), {
        status, headers: { "content-type": "application/json" },
      }));
    }
    return Promise.resolve(new Response(JSON.stringify({ access: "AAA", refresh: "RRR" }), {
      status: 200, headers: { "content-type": "application/json" },
    }));
  }) as unknown as typeof fetch;
}

function upstreamRegisterWithTokens() {
  // The gated backend returns a token pair WITH the 201 (Turnstile tokens are
  // single-use, so signup must be a single gated request).
  const f = vi.fn(() =>
    Promise.resolve(new Response(JSON.stringify({ access: "AAA", refresh: "RRR" }), {
      status: 201, headers: { "content-type": "application/json" },
    })),
  );
  global.fetch = f as unknown as typeof fetch;
  return f;
}

describe("registerAction — turnstile", () => {
  it("forwards the Turnstile token and uses the 201's token pair without a second login call", async () => {
    const f = upstreamRegisterWithTokens();

    await expect(
      registerAction({}, form({ ...VALID, "cf-turnstile-response": "tok-123" })),
    ).rejects.toThrow("NEXT_REDIRECT /account");

    expect(f).toHaveBeenCalledTimes(1); // register only — no /auth/token/ round-trip
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain("/auth/register/");
    expect(JSON.parse(String(init.body))).toMatchObject({ turnstile_token: "tok-123" });
    expect(setSpy).toHaveBeenCalledWith("access", "AAA");
    expect(setSpy).toHaveBeenCalledWith("refresh", "RRR");
  });

  it("omits turnstile_token when the widget did not run", async () => {
    const f = upstreamRegisterWithTokens();

    await expect(
      registerAction({}, form({ ...VALID })),
    ).rejects.toThrow("NEXT_REDIRECT /account");

    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).not.toHaveProperty("turnstile_token");
  });
});

describe("registerAction", () => {
  it("creates the account, signs the user in, and lands them on `next`", async () => {
    upstreamOk();

    await expect(
      registerAction({}, form({ ...VALID, next: "/account/orders" })),
    ).rejects.toThrow("NEXT_REDIRECT /account/orders");

    expect(setSpy).toHaveBeenCalledWith("access", "AAA");
    expect(setSpy).toHaveBeenCalledWith("refresh", "RRR");
  });

  it("re-validates `next` server-side", async () => {
    upstreamOk();
    await expect(
      registerAction({}, form({ ...VALID, next: "https://evil.example/pwn" })),
    ).rejects.toThrow("NEXT_REDIRECT /account");
  });

  it("forwards the optional fields the serializer accepts", async () => {
    const f = upstreamOk();

    await expect(
      registerAction({}, form({ ...VALID, last_name: "Lovelace", marketing_consent: "on" })),
    ).rejects.toThrow(/NEXT_REDIRECT/);

    const register = f.mock.calls.find((c) => String(c[0]).endsWith("/auth/register/"));
    const sent = JSON.parse(String(register![1]!.body));
    expect(sent).toMatchObject({
      email: "a@b.com", first_name: "Ada", last_name: "Lovelace", marketing_consent: true,
    });
  });

  it("treats an unticked consent checkbox as false, not missing", async () => {
    const f = upstreamOk();
    await expect(registerAction({}, form(VALID))).rejects.toThrow(/NEXT_REDIRECT/);
    const register = f.mock.calls.find((c) => String(c[0]).endsWith("/auth/register/"));
    expect(JSON.parse(String(register![1]!.body)).marketing_consent).toBe(false);
  });

  it("offers sign-in when the address already has an account", async () => {
    upstreamFail(400, { email: ["Account already exists"] });

    const state = await registerAction({}, form({ ...VALID, next: "/account/orders" }));

    expect(state.emailTaken).toBe(true);
    expect(state.error).toMatch(/already exists/i);
    // The page needs the destination preserved so its "sign in instead" link carries it.
    expect(state.next).toBe("/account/orders");
    expect(setSpy).not.toHaveBeenCalled();
  });

  it("shows Django's password rules so the user knows what to change", async () => {
    upstreamFail(400, { password: ["This password is too common."] });

    const state = await registerAction({}, form(VALID));

    expect(state.error).toMatch(/too common/i);
    expect(state.emailTaken).toBe(false);
  });

  it("keeps the entered name and email after a failure", async () => {
    upstreamFail(400, { password: ["Too short."] });

    const state = await registerAction({}, form({ ...VALID, last_name: "Lovelace" }));

    expect(state.email).toBe("a@b.com");
    expect(state.firstName).toBe("Ada");
    expect(state.lastName).toBe("Lovelace");
  });

  it("validates missing input without calling the API", async () => {
    const f = vi.fn();
    global.fetch = f as unknown as typeof fetch;

    const state = await registerAction({}, form({ email: "", password: "", first_name: "" }));

    expect(state.error).toBeTruthy();
    expect(f).not.toHaveBeenCalled();
  });

  it("sanitises a hostile `next` in the returned state too", async () => {
    upstreamFail(400, { password: ["Too short."] });
    const state = await registerAction({}, form({ ...VALID, next: "//evil.example" }));
    expect(state.next).toBe("/account");
  });
});
