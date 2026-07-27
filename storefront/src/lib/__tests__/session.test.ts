import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>([["access", "OLD"], ["refresh", "RRR"]]);
const setSpy = vi.fn((n: string, v: string) => store.set(n, v));

/** Simulates the Next 16 rule the whole design turns on: during Server Component
 * render, READING cookies works but MUTATING them throws. Flipped per-test to stand in
 * for "this code is running in an RSC". */
let cookieWritesAllowed = true;
function guardWrite() {
  if (!cookieWritesAllowed) {
    throw new Error("Cookies can only be modified in a Server Action or Route Handler");
  }
}

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => { guardWrite(); return setSpy(n, v); },
    delete: (n: string) => { guardWrite(); return store.delete(n); },
  }),
}));

/** Stands in for Next's redirect(), which works by THROWING NEXT_REDIRECT. Tests assert
 * on the thrown target, which is also how the real control flow behaves. */
class Redirected extends Error {
  constructor(public to: string) { super(`NEXT_REDIRECT ${to}`); }
}
vi.mock("next/navigation", () => ({
  redirect: (to: string) => { throw new Redirected(to); },
}));

import {
  fetchWithAuth, fetchWithAuthOrBounce, fetchWithAuthRaw, requireAuth,
} from "@/lib/session";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  setSpy.mockClear();
  store.set("access", "OLD");
  store.set("refresh", "RRR");
  cookieWritesAllowed = true;
});
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

describe("fetchWithAuth silent refresh", () => {
  it("refreshes once on a 401, stores the new access token, and retries", async () => {
    const calls: string[] = [];
    global.fetch = vi.fn((url: string, init?: RequestInit) => {
      calls.push(url);
      if (url.endsWith("/auth/me/") && new Headers(init?.headers).get("Authorization") === "Bearer OLD")
        return Promise.resolve(new Response("{}", { status: 401 }));
      if (url.endsWith("/auth/token/refresh/"))
        return Promise.resolve(new Response(JSON.stringify({ access: "NEW" }), { status: 200, headers: { "content-type": "application/json" } }));
      return Promise.resolve(new Response(JSON.stringify({ email: "a@b.com" }), { status: 200, headers: { "content-type": "application/json" } }));
    }) as unknown as typeof fetch;

    const data = await fetchWithAuth<{ email: string }>("/auth/me/");
    expect(data.email).toBe("a@b.com");
    expect(setSpy).toHaveBeenCalledWith("access", "NEW");
    expect(calls.some((u) => u.endsWith("/auth/token/refresh/"))).toBe(true);
  });

  it("persists a rotated refresh token returned by the refresh endpoint", async () => {
    // Backend has ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION: every refresh
    // returns a NEW refresh token and blacklists the old one. Failing to store the
    // rotation would leave a dead refresh cookie and force-log the user out.
    global.fetch = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/auth/me/") && new Headers(init?.headers).get("Authorization") === "Bearer OLD")
        return Promise.resolve(new Response("{}", { status: 401 }));
      if (url.endsWith("/auth/token/refresh/"))
        return Promise.resolve(new Response(JSON.stringify({ access: "NEW", refresh: "RRR2" }), { status: 200, headers: { "content-type": "application/json" } }));
      return Promise.resolve(new Response(JSON.stringify({ email: "a@b.com" }), { status: 200, headers: { "content-type": "application/json" } }));
    }) as unknown as typeof fetch;

    const data = await fetchWithAuth<{ email: string }>("/auth/me/");
    expect(data.email).toBe("a@b.com");
    expect(setSpy).toHaveBeenCalledWith("access", "NEW");
    expect(setSpy).toHaveBeenCalledWith("refresh", "RRR2");
  });
});

describe("fetchWithAuth misuse probe", () => {
  it("fails loudly BEFORE any network call when cookies are not writable", async () => {
    // The hazard is not the failed cookie write — it is the refresh POST. SimpleJWT
    // blacklists the old refresh token the instant it rotates, so a refresh an RSC
    // cannot persist has silently destroyed a 14-day session. Hence: no fetch at all.
    const f = vi.fn();
    global.fetch = f as unknown as typeof fetch;
    cookieWritesAllowed = false;

    await expect(fetchWithAuth("/auth/me/")).rejects.toThrow(/Server Component/);
    expect(f).not.toHaveBeenCalled();
  });

  it("names the safe alternative in the error message", async () => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    cookieWritesAllowed = false;
    await expect(fetchWithAuth("/auth/me/")).rejects.toThrow(/fetchWithAuthOrBounce/);
  });
});

describe("requireAuth", () => {
  it("returns the access token when one is present", async () => {
    await expect(requireAuth("/account")).resolves.toBe("OLD");
  });

  it("bounces through the renewal handler when only the refresh cookie survives", async () => {
    store.delete("access");
    await expect(requireAuth("/account/orders")).rejects.toThrow(
      "NEXT_REDIRECT /api/auth/refresh-redirect?next=%2Faccount%2Forders",
    );
  });

  it("sends a caller with neither cookie to login, preserving where they were going", async () => {
    store.delete("access");
    store.delete("refresh");
    await expect(requireAuth("/account/addresses")).rejects.toThrow(
      "NEXT_REDIRECT /login?next=%2Faccount%2Faddresses",
    );
  });
});

describe("fetchWithAuthOrBounce", () => {
  it("returns data when the access token is accepted", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ email: "a@b.com" }), {
        status: 200, headers: { "content-type": "application/json" },
      }),
    ) as unknown as typeof fetch;

    const data = await fetchWithAuthOrBounce<{ email: string }>("/auth/me/", "/account");
    expect(data.email).toBe("a@b.com");
  });

  it("bounces on a 401 WITHOUT touching the refresh endpoint or any cookie", async () => {
    // THE regression test for this whole item. A Server Component that refreshes in
    // place rotates the refresh token, fails to persist it, and silently ends the
    // session. So on 401: no /auth/token/refresh/ call, no cookie write — just a bounce
    // to the Route Handler that is allowed to do both.
    const urls: string[] = [];
    global.fetch = vi.fn((url: string) => {
      urls.push(url);
      return Promise.resolve(new Response("{}", { status: 401 }));
    }) as unknown as typeof fetch;

    await expect(fetchWithAuthOrBounce("/auth/me/", "/account")).rejects.toThrow(
      "NEXT_REDIRECT /api/auth/refresh-redirect?next=%2Faccount",
    );
    expect(urls.some((u) => u.includes("/auth/token/refresh/"))).toBe(false);
    expect(setSpy).not.toHaveBeenCalled();
  });

  it("sends a 401 with no refresh cookie to login instead of the renewal handler", async () => {
    store.delete("refresh");
    global.fetch = vi.fn().mockResolvedValue(
      new Response("{}", { status: 401 }),
    ) as unknown as typeof fetch;

    await expect(fetchWithAuthOrBounce("/auth/me/", "/account")).rejects.toThrow(
      "NEXT_REDIRECT /login?next=%2Faccount",
    );
  });

  it("lets a non-401 error through untouched", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "gone" }), {
        status: 404, headers: { "content-type": "application/json" },
      }),
    ) as unknown as typeof fetch;

    await expect(fetchWithAuthOrBounce("/orders/TC-9/", "/account")).rejects.toMatchObject({
      status: 404,
    });
  });

  it("is usable from a Server Component — no cookie write, so no probe trip", async () => {
    cookieWritesAllowed = false;
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200, headers: { "content-type": "application/json" },
      }),
    ) as unknown as typeof fetch;

    await expect(fetchWithAuthOrBounce("/auth/me/", "/account")).resolves.toEqual({ ok: true });
  });
});

describe("fetchWithAuthRaw", () => {
  const PDF = "%PDF-1.7";

  function invoiceFetch(firstAttempt: Response, secondAttempt: Response) {
    let attempts = 0;
    return vi.fn((url: string) => {
      if (url.endsWith("/auth/token/refresh/")) {
        return Promise.resolve(new Response(
          JSON.stringify({ access: "NEW", refresh: "RRR2" }),
          { status: 200, headers: { "content-type": "application/json" } },
        ));
      }
      attempts += 1;
      return Promise.resolve(attempts === 1 ? firstAttempt : secondAttempt);
    }) as unknown as typeof fetch;
  }

  it("passes a successful response straight through with its body unread", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(PDF, { status: 200, headers: { "content-type": "application/pdf" } }),
    ) as unknown as typeof fetch;

    const res = await fetchWithAuthRaw("/orders/TC-1/invoice.pdf");
    expect(res.status).toBe(200);
    expect(res.bodyUsed).toBe(false);
    expect(res.headers.get("content-type")).toBe("application/pdf");
    await expect(res.text()).resolves.toBe(PDF);
  });

  it("renews on a 401 and returns the response from a brand-new request", async () => {
    // An invoice link is an <a> hard navigation, so it can be clicked at minute 31 of a
    // perfectly good 14-day session. Without the retry that is a broken download.
    const first = new Response("unauthorised", { status: 401 });
    const second = new Response(PDF, {
      status: 200, headers: { "content-type": "application/pdf" },
    });
    global.fetch = invoiceFetch(first, second);

    const res = await fetchWithAuthRaw("/orders/TC-1/invoice.pdf");
    expect(res.status).toBe(200);
    await expect(res.text()).resolves.toBe(PDF);
    expect(setSpy).toHaveBeenCalledWith("access", "NEW");
    expect(setSpy).toHaveBeenCalledWith("refresh", "RRR2");
  });

  it("releases the rejected response's body rather than leaking the connection", async () => {
    const first = new Response("unauthorised", { status: 401 });
    global.fetch = invoiceFetch(first, new Response(PDF, { status: 200 }));

    await fetchWithAuthRaw("/orders/TC-1/invoice.pdf");
    expect(first.bodyUsed).toBe(true);
  });

  it("returns a non-ok retry response as-is, leaving the status mapping to the caller", async () => {
    // The invoice BFF turns 403 into 404 itself (no existence oracle), so the transport
    // must hand the 403 over intact rather than throwing.
    const first = new Response("unauthorised", { status: 401 });
    const second = new Response(JSON.stringify({ detail: "not yours" }), { status: 403 });
    global.fetch = invoiceFetch(first, second);

    const res = await fetchWithAuthRaw("/orders/TC-1/invoice.pdf");
    expect(res.status).toBe(403);
  });

  it("returns the 401 untouched when there is no refresh cookie to spend", async () => {
    store.delete("refresh");
    global.fetch = vi.fn().mockResolvedValue(
      new Response("unauthorised", { status: 401 }),
    ) as unknown as typeof fetch;

    const res = await fetchWithAuthRaw("/orders/TC-1/invoice.pdf");
    expect(res.status).toBe(401);
    expect(setSpy).not.toHaveBeenCalled();
  });

  it("trips the misuse probe before any network call", async () => {
    const f = vi.fn();
    global.fetch = f as unknown as typeof fetch;
    cookieWritesAllowed = false;

    await expect(fetchWithAuthRaw("/orders/TC-1/invoice.pdf")).rejects.toThrow(/Server Component/);
    expect(f).not.toHaveBeenCalled();
  });
});
