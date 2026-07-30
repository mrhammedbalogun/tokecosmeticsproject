import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

import { acceptInvite, adminLogin } from "@/lib/admin-session";

const originalFetch = global.fetch;
const originalSecret = process.env.ADMIN_BFF_SECRET;

function jar() {
  return {
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  } as never;
}

beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.clear();
});
afterEach(() => {
  global.fetch = originalFetch;
  if (originalSecret === undefined) delete process.env.ADMIN_BFF_SECRET;
  else process.env.ADMIN_BFF_SECRET = originalSecret;
  vi.restoreAllMocks();
});

function ok() {
  return new Response(JSON.stringify({ preauth_token: "PRE", expires_in: 600 }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function headersOf(mock: ReturnType<typeof vi.fn>): Headers {
  const [, init] = mock.mock.calls[0] as unknown as [string, RequestInit];
  return new Headers(init.headers);
}

describe("the admin BFF shared-secret header", () => {
  it("is sent on the staff login call", async () => {
    process.env.ADMIN_BFF_SECRET = "shhh";
    const fetchMock = vi.fn(async () => ok());
    global.fetch = fetchMock as unknown as typeof fetch;

    await adminLogin(jar(), { email: "a@b.c", password: "pw" });

    expect(headersOf(fetchMock).get("X-Admin-BFF-Secret")).toBe("shhh");
  });

  it("is sent on the accept-invite call", async () => {
    // The second endpoint with a single caller. Missing it here would leave the
    // siteverify cost open on the one public endpoint that CREATES administrators.
    process.env.ADMIN_BFF_SECRET = "shhh";
    const fetchMock = vi.fn(async () => ok());
    global.fetch = fetchMock as unknown as typeof fetch;

    await acceptInvite(jar(), { token: "t", password: "pw" });

    expect(headersOf(fetchMock).get("X-Admin-BFF-Secret")).toBe("shhh");
  });

  it("is omitted entirely when the secret is unset", async () => {
    // Not sent as an empty string: Django treats absent and empty identically, but an
    // empty header is a claim that there is a secret and it is blank. Omit it.
    delete process.env.ADMIN_BFF_SECRET;
    const fetchMock = vi.fn(async () => ok());
    global.fetch = fetchMock as unknown as typeof fetch;

    await adminLogin(jar(), { email: "a@b.c", password: "pw" });

    expect(headersOf(fetchMock).has("X-Admin-BFF-Secret")).toBe(false);
  });

  it("is NOT sent on the TOTP calls, which carry a preauth token instead", async () => {
    // Scope discipline. Those endpoints are not gated — they require a preauth token,
    // which is a real credential — and spraying the secret across every call widens its
    // exposure for nothing.
    process.env.ADMIN_BFF_SECRET = "shhh";
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ secret: "s", provisioning_uri: "u", issuer: "i" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const { enrolTotp } = await import("@/lib/admin-session");
    await enrolTotp("PREAUTH");

    expect(headersOf(fetchMock).has("X-Admin-BFF-Secret")).toBe(false);
  });
});
