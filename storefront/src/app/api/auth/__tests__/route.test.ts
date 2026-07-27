import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock next/headers cookies() so we can assert what the handler sets.
const store = new Map<string, string>();
const setSpy = vi.fn((name: string, value: string) => store.set(name, value));
const deleteSpy = vi.fn((name: string) => store.delete(name));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => setSpy(n, v),
    delete: (n: string) => deleteSpy(n),
  }),
}));

import { POST } from "@/app/api/auth/[action]/route";

const originalFetch = global.fetch;
beforeEach(() => {
  store.clear();
  setSpy.mockClear();
  deleteSpy.mockClear();
  process.env.API_URL = "http://backend:8000";
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

function upstream(status: number, body: unknown) {
  // 204/205/304 are "null body status" codes: the WHATWG Response constructor
  // (undici) throws if you pass a body with them, so send null for those.
  const nullBody = status === 204 || status === 205 || status === 304;
  global.fetch = vi.fn().mockResolvedValue(
    new Response(nullBody ? null : JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  ) as unknown as typeof fetch;
}
function req(body: unknown, headers: Record<string, string> = {}) {
  return new Request("http://localhost:3000/api/auth/login", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      // Browsers always send Origin on POST; the handler rejects requests without a
      // matching one (session fixation). Real callers are all same-origin fetches.
      origin: "http://localhost:3000",
      host: "localhost:3000",
      ...headers,
    },
    body: JSON.stringify(body),
  });
}

describe("auth BFF — same-origin gate", () => {
  // A cross-site form POST with the ATTACKER's credentials would otherwise get our
  // Set-Cookie response, logging the victim into the attacker's account; mergeGuestCart
  // then folds the victim's bag into it. SameSite=Lax does not prevent this, because
  // the attack needs no existing cookie — it is the response that does the damage.
  it("rejects a cross-site origin without calling upstream or setting cookies", async () => {
    upstream(200, { access: "AAA", refresh: "RRR" });
    const res = await POST(
      req({ email: "attacker@evil.com", password: "pw" }, { origin: "https://evil.example" }),
      { params: Promise.resolve({ action: "login" }) },
    );
    expect(res.status).toBe(403);
    expect(setSpy).not.toHaveBeenCalled();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("rejects a POST with no Origin header at all", async () => {
    upstream(200, { access: "AAA", refresh: "RRR" });
    const bare = new Request("http://localhost:3000/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json", host: "localhost:3000" },
      body: JSON.stringify({ email: "a@b.com", password: "pw" }),
    });
    const res = await POST(bare, { params: Promise.resolve({ action: "login" }) });
    expect(res.status).toBe(403);
    expect(setSpy).not.toHaveBeenCalled();
  });

  it("honours x-forwarded-host, since Vercel terminates in front of the handler", async () => {
    upstream(200, { access: "AAA", refresh: "RRR" });
    const fwd = new Request("http://internal/api/auth/login", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: "https://next.tokecosmetics.com",
        host: "internal",
        "x-forwarded-host": "next.tokecosmetics.com",
      },
      body: JSON.stringify({ email: "a@b.com", password: "pw" }),
    });
    const res = await POST(fwd, { params: Promise.resolve({ action: "login" }) });
    expect(res.status).toBe(200);
  });
});

describe("auth BFF", () => {
  it("login stores access+refresh cookies and does NOT leak tokens in the body", async () => {
    upstream(200, { access: "AAA", refresh: "RRR" });
    const res = await POST(req({ email: "a@b.com", password: "pw" }), { params: Promise.resolve({ action: "login" }) });
    expect(res.status).toBe(200);
    expect(setSpy).toHaveBeenCalledWith("access", "AAA");
    expect(setSpy).toHaveBeenCalledWith("refresh", "RRR");
    const json = await res.json();
    expect(JSON.stringify(json)).not.toContain("AAA");
    expect(JSON.stringify(json)).not.toContain("RRR");
  });

  it("login forwards a 401 as 401 without setting cookies", async () => {
    upstream(401, { detail: "No active account found with the given credentials" });
    const res = await POST(req({ email: "a@b.com", password: "bad" }), { params: Promise.resolve({ action: "login" }) });
    expect(res.status).toBe(401);
    expect(setSpy).not.toHaveBeenCalled();
  });

  it("logout clears cookies", async () => {
    store.set("access", "AAA");
    store.set("refresh", "RRR");
    upstream(205, {});
    const res = await POST(req({}), { params: Promise.resolve({ action: "logout" }) });
    expect(res.status).toBe(200);
    expect(deleteSpy).toHaveBeenCalledWith("access");
    expect(deleteSpy).toHaveBeenCalledWith("refresh");
  });

  it("register forwards the 400 duplicate-email error", async () => {
    upstream(400, { email: ["Account already exists"] });
    const res = await POST(req({ email: "a@b.com", password: "pw" }), { params: Promise.resolve({ action: "register" }) });
    expect(res.status).toBe(400);
    const json = await res.json();
    expect(json.email).toContain("Account already exists");
  });
});
