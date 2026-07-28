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

import { updateProfileAction } from "../actions";

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

describe("updateProfileAction", () => {
  it("PATCHes the editable fields to /auth/me/ with the session token", async () => {
    const f = upstream(200, {});

    const state = await updateProfileAction({}, form({
      first_name: "Ada", last_name: "Lovelace", phone: "+2348000000000",
      marketing_consent: "on",
    }));

    expect(state.saved).toBe(true);
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain("/auth/me/");
    expect(init.method).toBe("PATCH");
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer AAA");
    expect(JSON.parse(String(init.body))).toMatchObject({
      first_name: "Ada", last_name: "Lovelace", phone: "+2348000000000",
      marketing_consent: true,
    });
  });

  it("sends an explicit false for an unticked consent box, not an omission", async () => {
    const f = upstream(200, {});
    await updateProfileAction({}, form({ first_name: "Ada" }));
    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toMatchObject({ marketing_consent: false });
  });

  it("requires a first name without calling the API", async () => {
    const f = vi.fn();
    global.fetch = f as unknown as typeof fetch;
    const state = await updateProfileAction({}, form({ first_name: "  " }));
    expect(state.saved).toBeUndefined();
    expect(state.error).toBeTruthy();
    expect(f).not.toHaveBeenCalled();
  });

  it("surfaces DRF field errors verbatim", async () => {
    upstream(400, { phone: ["Enter a valid phone number."] });
    const state = await updateProfileAction({}, form({ first_name: "Ada", phone: "nope" }));
    expect(state.error).toMatch(/valid phone number/i);
  });
});
