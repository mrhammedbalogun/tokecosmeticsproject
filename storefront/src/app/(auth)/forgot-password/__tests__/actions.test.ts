import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { requestResetAction } from "../actions";

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

describe("requestResetAction", () => {
  it("posts the email plus the Turnstile token and reports the letter as sent", async () => {
    const f = upstream(200, { detail: "If that account exists, a reset link has been sent." });

    const state = await requestResetAction({}, form({
      email: "a@b.com", "cf-turnstile-response": "tok-1",
    }));

    expect(state.sent).toBe(true);
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toContain("/auth/password/reset/");
    expect(JSON.parse(String(init.body))).toMatchObject({
      email: "a@b.com", turnstile_token: "tok-1",
    });
  });

  it("omits turnstile_token when the widget did not run", async () => {
    const f = upstream(200, {});
    await requestResetAction({}, form({ email: "a@b.com" }));
    const [, init] = f.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).not.toHaveProperty("turnstile_token");
  });

  it("validates the email locally without calling the API", async () => {
    const f = vi.fn();
    global.fetch = f as unknown as typeof fetch;
    const state = await requestResetAction({}, form({}));
    expect(state.sent).toBeUndefined();
    expect(state.error).toBeTruthy();
    expect(f).not.toHaveBeenCalled();
  });

  it("shows wait-and-retry copy on a 429 — the throttle is the only signal", async () => {
    upstream(429, { detail: "Request was throttled." });
    const state = await requestResetAction({}, form({ email: "a@b.com" }));
    expect(state.sent).toBeUndefined();
    expect(state.error).toMatch(/too many|wait/i);
  });

  it("shows the verification message on a turnstile 403", async () => {
    upstream(403, { detail: "Human verification failed. Refresh the page and try again." });
    const state = await requestResetAction({}, form({ email: "a@b.com" }));
    expect(state.error).toMatch(/verification/i);
  });

  it("keeps the entered email after a failure", async () => {
    upstream(429, {});
    const state = await requestResetAction({}, form({ email: "keep@me.com" }));
    expect(state.email).toBe("keep@me.com");
  });
});
