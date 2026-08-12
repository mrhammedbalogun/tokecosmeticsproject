import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  acceptInvite,
  adminLogin,
  adminLogout,
  clearSession,
  confirmSecondFactor,
  enrolTotp,
  recoverTotp,
  requestEmailOtp,
  storePreauth,
  storeSession,
  type Jar,
} from "@/lib/admin-session";

/**
 * MUTUAL EXCLUSIVITY IS ENFORCED AT WRITE TIME. That is what makes "both cookie sets
 * present" an anomaly the gate can purge rather than an ambiguity it has to resolve — so
 * it is asserted on the writers, not inferred from the readers.
 */
type Entry = { value: string; opts?: Record<string, unknown> };

function fakeJar(initial: Record<string, string> = {}) {
  const store = new Map<string, Entry>(
    Object.entries(initial).map(([k, v]) => [k, { value: v }]),
  );
  const jar = {
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n)!.value } : undefined),
    set: (n: string, v: string, opts?: Record<string, unknown>) => {
      store.set(n, { value: v, opts });
    },
    delete: (n: string) => {
      store.delete(n);
    },
  };
  return { jar: jar as unknown as Jar, store };
}

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("cookie writers are mutually exclusive", () => {
  it("storing a preauth token clears any session pair", () => {
    const { jar, store } = fakeJar({ admin_access: "A", admin_refresh: "R" });
    storePreauth(jar, "PRE");
    expect(store.has("admin_access")).toBe(false);
    expect(store.has("admin_refresh")).toBe(false);
    expect(store.get("admin_preauth")?.value).toBe("PRE");
  });

  it("storing a session clears the preauth token", () => {
    const { jar, store } = fakeJar({ admin_preauth: "PRE" });
    storeSession(jar, "A", "R");
    expect(store.has("admin_preauth")).toBe(false);
    expect(store.get("admin_access")?.value).toBe("A");
    expect(store.get("admin_refresh")?.value).toBe("R");
  });

  it("clearSession removes the three session cookies and SPARES the device trust", () => {
    const { jar, store } = fakeJar({
      admin_access: "A",
      admin_refresh: "R",
      admin_preauth: "P",
      admin_device: "D",
    });
    clearSession(jar);
    // Signing out ends the session, not the browser's trust: the device cookie is a
    // pre-verified second factor, and only revocation/expiry/refusal may kill it.
    expect([...store.keys()]).toEqual(["admin_device"]);
  });

  it("writes every cookie httpOnly, SameSite=Strict, with a lifetime under its token's", () => {
    const { jar, store } = fakeJar();
    storeSession(jar, "A", "R");
    storePreauth(jar, "P");
    // Access 10 min < the backend's 15-min access token; refresh 12 h << 30 days;
    // preauth exactly the token's own 10 minutes.
    expect(store.get("admin_preauth")?.opts).toMatchObject({
      httpOnly: true,
      sameSite: "strict",
      path: "/",
      maxAge: 600,
    });
  });
});

describe("the ceremony", () => {
  it("step one stores ONLY a preauth token, even for an already-enrolled staff member", async () => {
    const { jar, store } = fakeJar();
    global.fetch = vi.fn(() =>
      Promise.resolve(
        jsonResponse({ preauth_token: "PRE", expires_in: 600, totp_enrolled: true }),
      ),
    ) as unknown as typeof fetch;

    const out = await adminLogin(jar, { email: "a@b.com", password: "pw" });

    expect(out.totp_enrolled).toBe(true);
    expect(store.get("admin_preauth")?.value).toBe("PRE");
    // The whole point of "one bootstrap path, not two": an enrolled account does NOT get
    // a session here.
    expect(store.has("admin_access")).toBe(false);
    expect(store.has("admin_refresh")).toBe(false);
  });

  it("forwards the Turnstile token as turnstile_token, and omits it entirely when absent", async () => {
    const bodies: string[] = [];
    global.fetch = vi.fn((_url: string, init?: RequestInit) => {
      bodies.push(String(init?.body));
      return Promise.resolve(jsonResponse({ preauth_token: "PRE", expires_in: 600 }));
    }) as unknown as typeof fetch;

    const { jar } = fakeJar();
    await adminLogin(jar, { email: "a@b.com", password: "pw" }, { turnstileToken: "TT" });
    await adminLogin(jar, { email: "a@b.com", password: "pw" });

    expect(JSON.parse(bodies[0])).toMatchObject({ turnstile_token: "TT" });
    expect(Object.keys(JSON.parse(bodies[1]))).not.toContain("turnstile_token");
  });

  it("enrolment authenticates with the preauth token and writes no cookie", async () => {
    const { jar, store } = fakeJar({ admin_preauth: "PRE" });
    let auth: string | null = null;
    global.fetch = vi.fn((_url: string, init?: RequestInit) => {
      auth = new Headers(init?.headers).get("Authorization");
      return Promise.resolve(
        jsonResponse({ secret: "S", provisioning_uri: "otpauth://x", issuer: "Toke" }),
      );
    }) as unknown as typeof fetch;

    await enrolTotp("PRE");
    expect(auth).toBe("Bearer PRE");
    expect(store.get("admin_preauth")?.value).toBe("PRE");
    expect(jar).toBeDefined();
  });

  it("confirm is the only call that produces a session, and it clears the preauth", async () => {
    const { jar, store } = fakeJar({ admin_preauth: "PRE" });
    global.fetch = vi.fn(() =>
      Promise.resolve(
        jsonResponse({ access: "A", refresh: "R", recovery_codes: ["c1", "c2"] }),
      ),
    ) as unknown as typeof fetch;

    const out = await confirmSecondFactor(jar, "PRE", { code: "123456" });

    expect(out.recovery_codes).toEqual(["c1", "c2"]);
    expect(store.get("admin_access")?.value).toBe("A");
    expect(store.get("admin_refresh")?.value).toBe("R");
    expect(store.has("admin_preauth")).toBe(false);
  });

  it("defaults the confirm body to the totp method so the old request shape survives", async () => {
    const { jar } = fakeJar({ admin_preauth: "PRE" });
    const bodies: string[] = [];
    global.fetch = vi.fn((_url: string, init?: RequestInit) => {
      bodies.push(String(init?.body));
      return Promise.resolve(jsonResponse({ access: "A", refresh: "R" }));
    }) as unknown as typeof fetch;

    await confirmSecondFactor(jar, "PRE", { code: "123456" });
    expect(JSON.parse(bodies[0])).toEqual({ method: "totp", code: "123456" });
  });

  it("recovery mints nothing and leaves the preauth token in place to re-enrol with", async () => {
    const { store } = fakeJar({ admin_preauth: "PRE" });
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse({ detail: "ok", enrolment_required: true })),
    ) as unknown as typeof fetch;

    const out = await recoverTotp("PRE", "abcd");

    expect(out.enrolment_required).toBe(true);
    expect(store.has("admin_access")).toBe(false);
    expect(store.get("admin_preauth")?.value).toBe("PRE");
  });

  it("accepting an invite lands in the same place as a password login: preauth only", async () => {
    const { jar, store } = fakeJar();
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse({ preauth_token: "PRE", expires_in: 600, detail: "ok" })),
    ) as unknown as typeof fetch;

    await acceptInvite(jar, { token: "T", password: "pw" }, { turnstileToken: "TT" });

    expect(store.get("admin_preauth")?.value).toBe("PRE");
    expect(store.has("admin_access")).toBe(false);
  });
});

describe("trusted devices", () => {
  it("login forwards the device cookie as device_token, and omits it when absent", async () => {
    const bodies: string[] = [];
    global.fetch = vi.fn((_url: string, init?: RequestInit) => {
      bodies.push(String(init?.body));
      return Promise.resolve(
        jsonResponse({ preauth_token: "PRE", expires_in: 600, device_trusted: true }),
      );
    }) as unknown as typeof fetch;

    const withDevice = fakeJar({ admin_device: "DEV" });
    await adminLogin(withDevice.jar, { email: "a@b.com", password: "pw" });
    const bare = fakeJar();
    await adminLogin(bare.jar, { email: "a@b.com", password: "pw" });

    expect(JSON.parse(bodies[0])).toMatchObject({ device_token: "DEV" });
    expect(Object.keys(JSON.parse(bodies[1]))).not.toContain("device_token");
  });

  it("a granted trust token is stored as a 30-day httpOnly cookie", async () => {
    const { jar, store } = fakeJar({ admin_preauth: "PRE" });
    global.fetch = vi.fn(() =>
      Promise.resolve(
        jsonResponse({
          access: "A",
          refresh: "R",
          device_token: "DEV",
          device_expires_in: 2592000,
        }),
      ),
    ) as unknown as typeof fetch;

    await confirmSecondFactor(jar, "PRE", { code: "123456", trustDevice: true });

    expect(store.get("admin_device")?.value).toBe("DEV");
    expect(store.get("admin_device")?.opts).toMatchObject({
      httpOnly: true,
      sameSite: "strict",
      maxAge: 2592000,
    });
  });

  it("a trusted-device confirm reads the cookie itself and sends no code", async () => {
    const { jar, store } = fakeJar({ admin_preauth: "PRE", admin_device: "DEV" });
    const bodies: string[] = [];
    global.fetch = vi.fn((_url: string, init?: RequestInit) => {
      bodies.push(String(init?.body));
      return Promise.resolve(jsonResponse({ access: "A", refresh: "R" }));
    }) as unknown as typeof fetch;

    await confirmSecondFactor(jar, "PRE", { method: "trusted_device" });

    expect(JSON.parse(bodies[0])).toEqual({
      method: "trusted_device",
      device_token: "DEV",
    });
    expect(store.get("admin_access")?.value).toBe("A");
  });

  it("a REFUSED trusted-device redemption drops the dead cookie", async () => {
    const { jar, store } = fakeJar({ admin_preauth: "PRE", admin_device: "DEV" });
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse({ detail: "nope" }, 401)),
    ) as unknown as typeof fetch;

    await expect(
      confirmSecondFactor(jar, "PRE", { method: "trusted_device" }),
    ).rejects.toMatchObject({ status: 401 });
    // The backend voted it dead; keeping it would re-fail every future login.
    expect(store.has("admin_device")).toBe(false);
    expect(store.has("admin_access")).toBe(false);
  });

  it("a refused CODE leaves the device cookie alone", async () => {
    const { jar, store } = fakeJar({ admin_preauth: "PRE", admin_device: "DEV" });
    global.fetch = vi.fn(() =>
      Promise.resolve(jsonResponse({ detail: "wrong code" }, 401)),
    ) as unknown as typeof fetch;

    await expect(
      confirmSecondFactor(jar, "PRE", { code: "000000" }),
    ).rejects.toMatchObject({ status: 401 });
    expect(store.get("admin_device")?.value).toBe("DEV");
  });
});

describe("the email-code send", () => {
  it("authenticates with the preauth token and writes no cookie", async () => {
    let auth: string | null = null;
    global.fetch = vi.fn((_url: string, init?: RequestInit) => {
      auth = new Headers(init?.headers).get("Authorization");
      return Promise.resolve(
        jsonResponse({ detail: "sent", retry_after: 60, expires_in: 300 }),
      );
    }) as unknown as typeof fetch;

    const out = await requestEmailOtp("PRE");
    expect(auth).toBe("Bearer PRE");
    expect(out.retry_after).toBe(60);
  });
});

describe("sign-out", () => {
  it("blacklists the refresh token and clears every cookie", async () => {
    const { jar, store } = fakeJar({ admin_access: "A", admin_refresh: "R" });
    const bodies: string[] = [];
    global.fetch = vi.fn((url: string, init?: RequestInit) => {
      expect(url).toContain("/auth/logout/");
      bodies.push(String(init?.body));
      return Promise.resolve(new Response(null, { status: 205 }));
    }) as unknown as typeof fetch;

    await adminLogout(jar);

    expect(JSON.parse(bodies[0])).toEqual({ refresh: "R" });
    expect(store.size).toBe(0);
  });

  it("clears the cookies even when the backend call fails", async () => {
    const { jar, store } = fakeJar({ admin_access: "A", admin_refresh: "R" });
    global.fetch = vi.fn(() => Promise.reject(new Error("network"))) as unknown as typeof fetch;

    await expect(adminLogout(jar)).resolves.toBeUndefined();
    expect(store.size).toBe(0);
  });
});
