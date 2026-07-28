import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { confirmResetAction } from "../actions";

const originalFetch = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; });
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

const VALID = {
  uid: "MTI", token: "tok-abc", password: "N3w-Str0ng-Pass!", confirm: "N3w-Str0ng-Pass!",
};

describe("confirmResetAction", () => {
  it("posts uid, token and password, and reports done", async () => {
    const f = upstream(200, {});

    const state = await confirmResetAction({}, form(VALID));

    expect(state.done).toBe(true);
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain("/auth/password/reset/confirm/");
    expect(JSON.parse(String(init.body))).toMatchObject({
      uid: "MTI", token: "tok-abc", password: "N3w-Str0ng-Pass!",
    });
  });

  it("never sends the confirm field upstream — it is a UI-only check", async () => {
    const f = upstream(200, {});
    await confirmResetAction({}, form(VALID));
    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).not.toHaveProperty("confirm");
  });

  it("rejects mismatched passwords locally without calling the API", async () => {
    const f = vi.fn();
    global.fetch = f as unknown as typeof fetch;
    const state = await confirmResetAction({}, form({ ...VALID, confirm: "different" }));
    expect(state.done).toBeUndefined();
    expect(state.error).toMatch(/match/i);
    expect(f).not.toHaveBeenCalled();
  });

  it("rejects a missing uid/token pair as an invalid link, without calling the API", async () => {
    const f = vi.fn();
    global.fetch = f as unknown as typeof fetch;
    const state = await confirmResetAction(
      {}, form({ password: VALID.password, confirm: VALID.confirm }),
    );
    expect(state.error).toMatch(/link/i);
    expect(f).not.toHaveBeenCalled();
  });

  it("echoes Django's password validators so the user knows what to change", async () => {
    upstream(400, { password: ["This password is too common."] });
    const state = await confirmResetAction({}, form(VALID));
    expect(state.error).toMatch(/too common/);
  });

  it("surfaces an expired link as its own outcome", async () => {
    upstream(400, { detail: "Invalid or expired reset link." });
    const state = await confirmResetAction({}, form(VALID));
    expect(state.error).toMatch(/invalid or expired/i);
  });
});
