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
function req(body: unknown) {
  return new Request("http://localhost:3000/api/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

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

/**
 * Merging the guest cart is a property of AUTHENTICATING, not of whichever page
 * remembered to call it. It used to live in checkout's SignInStep, which meant any new
 * sign-in surface (the Plan-15 /login and /register pages) would silently drop a
 * shopper's bag — the exact bug the Plan-14 walkthrough caught, waiting to happen again
 * on a different route.
 *
 * Moving it here also kills a latent race: SignInStep snapshotted `cart.id` from
 * react-query state, so a shopper who submitted before that query resolved got
 * `undefined` and no merge at all. The cookie has no such race — it is the authoritative
 * copy, and the client's value was only ever derived from it.
 */
describe("auth BFF merges the guest cart", () => {
  function routeCalls() {
    return (global.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.map(
      (c) => String(c[0]),
    );
  }

  function upstreamSequence() {
    global.fetch = vi.fn((url: string) => {
      const body = String(url).includes("/cart/merge/")
        ? { id: "merged-cart" }
        : { access: "AAA", refresh: "RRR" };
      return Promise.resolve(new Response(JSON.stringify(body), {
        status: 200, headers: { "content-type": "application/json" },
      }));
    }) as unknown as typeof fetch;
  }

  it("merges on login when a guest cart cookie is present", async () => {
    store.set("cart_id", "guest-cart-1");
    upstreamSequence();

    await POST(req({ email: "a@b.com", password: "pw" }),
               { params: Promise.resolve({ action: "login" }) });

    expect(routeCalls().some((u) => u.includes("/cart/merge/"))).toBe(true);
  });

  it("merges on register too", async () => {
    store.set("cart_id", "guest-cart-1");
    upstreamSequence();

    await POST(req({ email: "a@b.com", password: "pw", first_name: "A" }),
               { params: Promise.resolve({ action: "register" }) });

    expect(routeCalls().some((u) => u.includes("/cart/merge/"))).toBe(true);
  });

  it("does not call merge when there is no guest cart", async () => {
    upstreamSequence();

    await POST(req({ email: "a@b.com", password: "pw" }),
               { params: Promise.resolve({ action: "login" }) });

    expect(routeCalls().some((u) => u.includes("/cart/merge/"))).toBe(false);
  });

  it("stores the merged cart id so the browser stops pointing at the spent guest cart", async () => {
    store.set("cart_id", "guest-cart-1");
    upstreamSequence();

    await POST(req({ email: "a@b.com", password: "pw" }),
               { params: Promise.resolve({ action: "login" }) });

    expect(setSpy).toHaveBeenCalledWith("cart_id", "merged-cart");
  });

  it("still reports a SUCCESSFUL login when the merge fails", async () => {
    // The handler's catch-all turns an ApiError into a failure response. If a merge
    // error escaped, the user would be told login failed while actually being logged in
    // — cookies set, form showing an error. Best-effort means locally swallowed.
    store.set("cart_id", "guest-cart-1");
    global.fetch = vi.fn((url: string) => {
      if (String(url).includes("/cart/merge/")) {
        return Promise.resolve(new Response(JSON.stringify({ detail: "boom" }), {
          status: 500, headers: { "content-type": "application/json" },
        }));
      }
      return Promise.resolve(new Response(JSON.stringify({ access: "AAA", refresh: "RRR" }), {
        status: 200, headers: { "content-type": "application/json" },
      }));
    }) as unknown as typeof fetch;

    const res = await POST(req({ email: "a@b.com", password: "pw" }),
                           { params: Promise.resolve({ action: "login" }) });

    expect(res.status).toBe(200);
    expect(setSpy).toHaveBeenCalledWith("access", "AAA");
  });

  it("does not merge on refresh — no identity transition, and it runs constantly", async () => {
    store.set("cart_id", "guest-cart-1");
    store.set("refresh", "RRR");
    upstreamSequence();

    await POST(req({}), { params: Promise.resolve({ action: "refresh" }) });

    expect(routeCalls().some((u) => u.includes("/cart/merge/"))).toBe(false);
  });

  it("logout drops the cart cookie so a signed-out browser holds no user-cart id", async () => {
    store.set("cart_id", "some-cart");
    store.set("access", "AAA");
    store.set("refresh", "RRR");
    upstream(200, {});

    await POST(req({}), { params: Promise.resolve({ action: "logout" }) });

    expect(deleteSpy).toHaveBeenCalledWith("cart_id");
  });
});
