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

import { acceptInviteAction } from "../actions";

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

const GOOD = { token: "TKN", password: "s3cret-passw0rd", password_confirm: "s3cret-passw0rd" };

describe("accepting a staff invite", () => {
  it("lands in the same place a password login does: a preauth token, owing a second factor", async () => {
    let body = "";
    global.fetch = vi.fn((url: string, init?: RequestInit) => {
      expect(url).toContain("/admin/staff/invites/accept/");
      body = String(init?.body);
      return Promise.resolve(jsonResponse({ preauth_token: "PRE", expires_in: 600 }));
    }) as unknown as typeof fetch;

    const to = await redirectFrom(() =>
      acceptInviteAction({}, form({ ...GOOD, "cf-turnstile-response": "TT" })),
    );

    expect(to).toBe("/totp?setup=1");
    expect(store.get("admin_preauth")).toBe("PRE");
    expect(store.has("admin_access")).toBe(false);
    expect(JSON.parse(body)).toMatchObject({ token: "TKN", turnstile_token: "TT" });
  });

  it("catches a password mismatch BEFORE spending the single-use invite", async () => {
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy as unknown as typeof fetch;

    const state = await acceptInviteAction(
      {},
      form({ ...GOOD, password_confirm: "different" }),
    );

    expect(state.error).toMatch(/do not match/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("refuses a link with no token at all, without calling the API", async () => {
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy as unknown as typeof fetch;
    const state = await acceptInviteAction({}, form({ ...GOOD, token: "" }));
    expect(state.error).toMatch(/not valid/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("echoes Django's password validators verbatim — they are the instruction", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse({ password: ["This password is too short."] }, 400)),
    ) as unknown as typeof fetch;

    const state = await acceptInviteAction({}, form(GOOD));
    expect(state.error).toBe("This password is too short.");
    expect(store.size).toBe(0);
  });

  it("passes the backend's one uniform message through for unknown/revoked/used tokens", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(
        jsonResponse(["That invite link is not valid. Ask for a new one."], 400),
      ),
    ) as unknown as typeof fetch;

    const state = await acceptInviteAction({}, form(GOOD));
    expect(state.error).toMatch(/not valid|went wrong/i);
  });
});
