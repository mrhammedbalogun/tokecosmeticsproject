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

import { confirmAction, emailOtpAction, enrolAction, recoveryAction } from "../actions";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.clear();
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

function form(fields: Record<string, string> = {}): FormData {
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

describe("enrolment", () => {
  it("returns the secret and provisioning URI, authenticating with the preauth cookie", async () => {
    store.set("admin_preauth", "PRE");
    let auth: string | null = null;
    global.fetch = vi.fn((url: string, init?: RequestInit) => {
      expect(url).toContain("/auth/admin-totp/enrol/");
      auth = new Headers(init?.headers).get("Authorization");
      return Promise.resolve(
        jsonResponse({ secret: "SEC", provisioning_uri: "otpauth://totp/x", issuer: "Toke" }),
      );
    }) as unknown as typeof fetch;

    const state = await enrolAction();
    expect(auth).toBe("Bearer PRE");
    expect(state.enrolment?.secret).toBe("SEC");
  });

  it("explains a 409 instead of showing a raw conflict", async () => {
    store.set("admin_preauth", "PRE");
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse({ detail: "already" }, 409)),
    ) as unknown as typeof fetch;

    const state = await enrolAction();
    expect(state.error).toMatch(/already set up/i);
  });
});

describe("confirm — the only step that can produce a session", () => {
  it("stores the pair, clears the preauth, and shows the recovery codes ONCE", async () => {
    store.set("admin_preauth", "PRE");
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse({ access: "A", refresh: "R", recovery_codes: ["x", "y"] })),
    ) as unknown as typeof fetch;

    const state = await confirmAction({}, form({ code: "123456", next: "/orders" }));

    // No redirect: redirecting past the codes would throw away the only copy of them.
    expect(state.recoveryCodes).toEqual(["x", "y"]);
    expect(state.next).toBe("/orders");
    expect(store.get("admin_access")).toBe("A");
    expect(store.get("admin_refresh")).toBe("R");
    expect(store.has("admin_preauth")).toBe(false);
  });

  it("redirects straight through on an ordinary login (no new codes)", async () => {
    store.set("admin_preauth", "PRE");
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse({ access: "A", refresh: "R" })),
    ) as unknown as typeof fetch;

    expect(await redirectFrom(() => confirmAction({}, form({ code: "123456", next: "/orders" })))).toBe(
      "/orders",
    );
    expect(store.get("admin_access")).toBe("A");
  });

  it("echoes the backend's single uniform rejection message", async () => {
    store.set("admin_preauth", "PRE");
    global.fetch = vi.fn(() =>
      Promise.resolve(
        jsonResponse({ detail: "That code is not valid. Check your authenticator app and try again." }, 401),
      ),
    ) as unknown as typeof fetch;

    // A 401 here means the PREAUTH TOKEN is dead, which is the same status the backend
    // uses for a wrong code — so the safe reading is "start again", and the cookie goes.
    expect(await redirectFrom(() => confirmAction({}, form({ code: "000000" })))).toBe("/login");
    expect(store.size).toBe(0);
  });

  it("reports the per-user hourly hard deny as what it is", async () => {
    store.set("admin_preauth", "PRE");
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse({ detail: "throttled" }, 429)),
    ) as unknown as typeof fetch;

    const state = await confirmAction({}, form({ code: "123456" }));
    expect(state.error).toMatch(/locked for up to an hour/i);
  });

  it("forwards the method and the trust checkbox to the backend", async () => {
    store.set("admin_preauth", "PRE");
    let body: unknown;
    global.fetch = vi.fn((_url: string, init?: RequestInit) => {
      body = JSON.parse(String(init?.body));
      return Promise.resolve(jsonResponse({ access: "A", refresh: "R" }));
    }) as unknown as typeof fetch;

    await redirectFrom(() =>
      confirmAction({}, form({ code: "123456", method: "email", trust_device: "on" })),
    );
    expect(body).toEqual({ method: "email", code: "123456", trust_device: true });
  });

  it("treats an unknown method value as totp — the backend re-derives anyway", async () => {
    store.set("admin_preauth", "PRE");
    let body: unknown;
    global.fetch = vi.fn((_url: string, init?: RequestInit) => {
      body = JSON.parse(String(init?.body));
      return Promise.resolve(jsonResponse({ access: "A", refresh: "R" }));
    }) as unknown as typeof fetch;

    await redirectFrom(() =>
      confirmAction({}, form({ code: "123456", method: "trusted_device" })),
    );
    // The form can never claim the trusted-device method: that path belongs to the
    // login action, which reads the httpOnly cookie itself.
    expect(body).toEqual({ method: "totp", code: "123456" });
  });

  it("refuses an empty code without spending a guess", async () => {
    store.set("admin_preauth", "PRE");
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy as unknown as typeof fetch;
    const state = await confirmAction({}, form({ code: "" }));
    expect(state.error).toMatch(/six-digit/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("bounces to /login with everything cleared when the preauth cookie is gone", async () => {
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy as unknown as typeof fetch;
    expect(await redirectFrom(() => confirmAction({}, form({ code: "123456" })))).toBe("/login");
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("the email-code send", () => {
  it("asks the backend to mail a code, authenticating with the preauth cookie", async () => {
    store.set("admin_preauth", "PRE");
    let auth: string | null = null;
    global.fetch = vi.fn((url: string, init?: RequestInit) => {
      expect(url).toContain("/auth/admin-email-otp/request/");
      auth = new Headers(init?.headers).get("Authorization");
      return Promise.resolve(jsonResponse({ detail: "sent", retry_after: 60, expires_in: 300 }));
    }) as unknown as typeof fetch;

    const state = await emailOtpAction();
    expect(auth).toBe("Bearer PRE");
    expect(state.sent).toBe(true);
    expect(state.retryAfter).toBe(60);
  });

  it("explains a 409 — the account is on the authenticator method", async () => {
    store.set("admin_preauth", "PRE");
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse({ detail: "already" }, 409)),
    ) as unknown as typeof fetch;

    const state = await emailOtpAction();
    expect(state.error).toMatch(/already set up/i);
    expect(state.sent).toBeUndefined();
  });

  it("bounces to /login when the preauth cookie is gone", async () => {
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy as unknown as typeof fetch;
    await expect(emailOtpAction()).rejects.toMatchObject({
      message: expect.stringContaining("/login"),
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("recovery codes", () => {
  it("mints nothing, keeps the preauth cookie, and returns to enrolment", async () => {
    store.set("admin_preauth", "PRE");
    global.fetch = vi.fn((url: string) => {
      expect(url).toContain("/auth/admin-totp/recovery/");
      return Promise.resolve(jsonResponse({ detail: "ok", enrolment_required: true }));
    }) as unknown as typeof fetch;

    const to = await redirectFrom(() => recoveryAction({}, form({ code: "abcd", next: "/orders" })));

    expect(to).toBe(`/totp?next=${encodeURIComponent("/orders")}&setup=1`);
    expect(store.get("admin_preauth")).toBe("PRE");
    expect(store.has("admin_access")).toBe(false);
  });

  it("refuses an empty code without calling the API", async () => {
    store.set("admin_preauth", "PRE");
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy as unknown as typeof fetch;
    const state = await recoveryAction({}, form({ code: "" }));
    expect(state.error).toMatch(/recovery code/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
