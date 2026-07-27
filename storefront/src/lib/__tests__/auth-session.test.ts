import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>();
const setSpy = vi.fn((n: string, v: string) => store.set(n, v));
const deleteSpy = vi.fn((n: string) => store.delete(n));
const jar = {
  get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
  set: (n: string, v: string) => setSpy(n, v),
  delete: (n: string) => deleteSpy(n),
};

import { clearTokens, establishSession, type Jar } from "@/lib/auth-session";

/** The real Jar is Next's cookie store (iterable, getAll, size…); these tests only
 * exercise get/set/delete, so the stub goes through `unknown` deliberately. */
const asJar = jar as unknown as Jar;

const originalFetch = global.fetch;
beforeEach(() => {
  store.clear();
  setSpy.mockClear();
  deleteSpy.mockClear();
  process.env.API_URL = "http://backend:8000";
});
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

/** Token endpoint succeeds; the merge endpoint echoes a new cart id. */
function upstreamOk() {
  const f = vi.fn((url: string, _init?: RequestInit) => {
    const body = String(url).includes("/cart/merge/")
      ? { id: "merged-cart" }
      : { access: "AAA", refresh: "RRR" };
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: 200, headers: { "content-type": "application/json" },
    }));
  });
  global.fetch = f as unknown as typeof fetch;
  return f;
}

describe("establishSession", () => {
  it("exchanges credentials for a token pair and persists both cookies", async () => {
    upstreamOk();
    const tokens = await establishSession(asJar, { email: "a@b.com", password: "pw" });

    expect(tokens.access).toBe("AAA");
    expect(setSpy).toHaveBeenCalledWith("access", "AAA");
    expect(setSpy).toHaveBeenCalledWith("refresh", "RRR");
  });

  it("merges a guest cart and repoints the cookie at the survivor", async () => {
    store.set("cart_id", "guest-cart-1");
    const f = upstreamOk();

    await establishSession(asJar, { email: "a@b.com", password: "pw" });

    expect(f.mock.calls.some((c) => String(c[0]).includes("/cart/merge/"))).toBe(true);
    expect(setSpy).toHaveBeenCalledWith("cart_id", "merged-cart");
  });

  it("forwards the country cookie on the merge", async () => {
    // Without this, apiFetch defaults X-Country to NG and the backend's get_or_create
    // mints an NG cart for a UK shopper who has no user cart yet. Previously unpinned by
    // any test, which is exactly how an extraction loses it.
    store.set("cart_id", "guest-cart-1");
    store.set("country", "GB");
    const f = upstreamOk();

    await establishSession(asJar, { email: "a@b.com", password: "pw" });

    const merge = f.mock.calls.find((c) => String(c[0]).includes("/cart/merge/"));
    expect(new Headers(merge![1]!.headers).get("X-Country")).toBe("GB");
  });

  it("uses the token from the login response, not the cookie jar, for the merge", async () => {
    // Mid-handler the jar still reflects the INCOMING request — jar.set only stages an
    // outgoing cookie — so reading the access cookie back would send a stale or absent
    // token and the merge would silently 401.
    store.set("cart_id", "guest-cart-1");
    store.set("access", "STALE-FROM-INCOMING-REQUEST");
    const f = upstreamOk();

    await establishSession(asJar, { email: "a@b.com", password: "pw" });

    const merge = f.mock.calls.find((c) => String(c[0]).includes("/cart/merge/"));
    expect(new Headers(merge![1]!.headers).get("Authorization")).toBe("Bearer AAA");
  });

  it("does not call merge when the browser holds no guest cart", async () => {
    const f = upstreamOk();
    await establishSession(asJar, { email: "a@b.com", password: "pw" });
    expect(f.mock.calls.some((c) => String(c[0]).includes("/cart/merge/"))).toBe(false);
  });

  it("still establishes the session when the merge fails", async () => {
    // A merge error must never surface as a failed login: the user would be told sign-in
    // failed while actually being signed in, cookies and all.
    store.set("cart_id", "guest-cart-1");
    global.fetch = vi.fn((url: string) => {
      if (String(url).includes("/cart/merge/")) {
        return Promise.resolve(new Response(JSON.stringify({ detail: "boom" }), { status: 500 }));
      }
      return Promise.resolve(new Response(JSON.stringify({ access: "AAA", refresh: "RRR" }), {
        status: 200, headers: { "content-type": "application/json" },
      }));
    }) as unknown as typeof fetch;

    await expect(
      establishSession(asJar, { email: "a@b.com", password: "pw" }),
    ).resolves.toMatchObject({ access: "AAA" });
    expect(setSpy).toHaveBeenCalledWith("access", "AAA");
  });

  it("propagates a rejected credential so the caller can show an error", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "No active account found with the given credentials" }), {
        status: 401, headers: { "content-type": "application/json" },
      }),
    ) as unknown as typeof fetch;

    await expect(
      establishSession(asJar, { email: "a@b.com", password: "bad" }),
    ).rejects.toMatchObject({ status: 401 });
    expect(setSpy).not.toHaveBeenCalled();
  });
});

describe("clearTokens", () => {
  it("drops both tokens and the cart pointer", async () => {
    clearTokens(asJar);
    expect(deleteSpy).toHaveBeenCalledWith("access");
    expect(deleteSpy).toHaveBeenCalledWith("refresh");
    expect(deleteSpy).toHaveBeenCalledWith("cart_id");
  });
});
