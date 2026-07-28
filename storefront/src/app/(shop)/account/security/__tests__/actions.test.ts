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

class Redirected extends Error {
  constructor(public to: string) { super(`NEXT_REDIRECT ${to}`); }
}
vi.mock("next/navigation", () => ({
  redirect: (to: string) => { throw new Redirected(to); },
}));

import { changePasswordAction, deleteAccountAction } from "../actions";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.clear();
  store.set("access", "AAA");
  store.set("refresh", "RRR");
  setSpy.mockClear();
  deleteSpy.mockClear();
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

describe("changePasswordAction", () => {
  const VALID = {
    old_password: "Old-Pass-1!", new_password: "New-Pass-2!", confirm: "New-Pass-2!",
  };

  it("posts old and new password and reports the change", async () => {
    const f = upstream(200, { detail: "Password updated." });

    const state = await changePasswordAction({}, form(VALID));

    expect(state.changed).toBe(true);
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain("/auth/password/change/");
    expect(JSON.parse(String(init.body))).toEqual({
      old_password: "Old-Pass-1!", new_password: "New-Pass-2!",
    });
  });

  it("rejects mismatched passwords locally without calling the API", async () => {
    const f = vi.fn();
    global.fetch = f as unknown as typeof fetch;
    const state = await changePasswordAction({}, form({ ...VALID, confirm: "other" }));
    expect(state.error).toMatch(/match/i);
    expect(f).not.toHaveBeenCalled();
  });

  it("surfaces a wrong current password verbatim", async () => {
    upstream(400, { old_password: ["Current password is incorrect."] });
    const state = await changePasswordAction({}, form(VALID));
    expect(state.error).toMatch(/current password is incorrect/i);
  });

  it("surfaces Django's password validators for the new password", async () => {
    upstream(400, { new_password: ["This password is too common."] });
    const state = await changePasswordAction({}, form(VALID));
    expect(state.error).toMatch(/too common/);
  });
});

describe("deleteAccountAction", () => {
  const VALID = { password: "My-Pass-1!", confirm_phrase: "DELETE" };

  it("posts the password, clears the session cookies, and redirects home", async () => {
    const f = upstream(200, { detail: "Account scheduled for deletion." });

    await expect(deleteAccountAction({}, form(VALID))).rejects.toThrow("NEXT_REDIRECT /");

    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain("/auth/account/delete/");
    expect(JSON.parse(String(init.body))).toEqual({ password: "My-Pass-1!" });
    expect(deleteSpy).toHaveBeenCalledWith("access");
    expect(deleteSpy).toHaveBeenCalledWith("refresh");
  });

  it("requires the typed DELETE phrase server-side, without calling the API", async () => {
    // The action is a public POST endpoint; the client-side gate is UX, not a guard.
    const f = vi.fn();
    global.fetch = f as unknown as typeof fetch;
    const state = await deleteAccountAction({}, form({ ...VALID, confirm_phrase: "delete please" }));
    expect(state.error).toMatch(/DELETE/);
    expect(f).not.toHaveBeenCalled();
  });

  it("surfaces a wrong password and keeps the session intact", async () => {
    upstream(400, { password: ["Password is incorrect."] });
    const state = await deleteAccountAction({}, form(VALID));
    expect(state.error).toMatch(/password is incorrect/i);
    // The dev-time probe deletes its sentinel cookie on every writing fetch —
    // what must survive a failed attempt is the SESSION pair.
    expect(deleteSpy).not.toHaveBeenCalledWith("access");
    expect(deleteSpy).not.toHaveBeenCalledWith("refresh");
  });
});
