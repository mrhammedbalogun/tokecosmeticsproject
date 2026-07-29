import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

/**
 * The gate matrix again, this time as BEHAVIOUR — real cookie reads and real redirects
 * (thrown, as Next's `redirect()` throws). `auth-guard.test.ts` proves the decision; this
 * proves the acting on it.
 *
 * The `cookieWritesAllowed` flag simulates the Next 16 rule the whole design turns on:
 * during Server Component render, READING cookies works but MUTATING them throws. It is
 * what the purge-handler indirection exists for.
 */
const store = new Map<string, string>();
const setSpy = vi.fn((n: string, v: string) => store.set(n, v));
const deleteSpy = vi.fn((n: string) => store.delete(n));

let cookieWritesAllowed = true;
function guardWrite() {
  if (!cookieWritesAllowed) {
    throw new Error("Cookies can only be modified in a Server Action or Route Handler");
  }
}

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => {
      guardWrite();
      return setSpy(n, v);
    },
    delete: (n: string) => {
      guardWrite();
      return deleteSpy(n);
    },
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

import {
  RscCookieWriteError,
  fetchWithAuth,
  fetchWithAuthOrBounce,
  gatePage,
  requireAdmin,
  requirePreauth,
} from "@/lib/session";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.clear();
  setSpy.mockClear();
  deleteSpy.mockClear();
  cookieWritesAllowed = true;
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

async function redirectFrom(fn: () => Promise<unknown>): Promise<string> {
  try {
    await fn();
  } catch (e) {
    if (e instanceof Redirected) return e.to;
    throw e;
  }
  throw new Error("expected a redirect");
}

describe("requireAdmin — the app-route gate", () => {
  it("returns the access token when the session is whole", async () => {
    store.set("admin_access", "A");
    store.set("admin_refresh", "R");
    await expect(requireAdmin("/orders")).resolves.toBe("A");
  });

  it("sends a cookieless request to /login carrying where it was going", async () => {
    expect(await redirectFrom(() => requireAdmin("/orders/42"))).toBe(
      `/login?next=${encodeURIComponent("/orders/42")}`,
    );
  });

  it("sends a preauth-only request to the TOTP step, not to /login", async () => {
    store.set("admin_preauth", "P");
    expect(await redirectFrom(() => requireAdmin("/orders"))).toBe("/totp");
  });

  it("bounces a stale access token through the renewal handler", async () => {
    store.set("admin_refresh", "R");
    expect(await redirectFrom(() => requireAdmin("/orders"))).toBe(
      `/api/auth/refresh-redirect?next=${encodeURIComponent("/orders")}`,
    );
  });

  it("sends the anomaly to the purge handler — it cannot delete cookies itself", async () => {
    store.set("admin_access", "A");
    store.set("admin_refresh", "R");
    store.set("admin_preauth", "P");
    // NOT a `jar.delete()` here: this runs during Server Component render, where a cookie
    // write throws (and did — the anomaly answered 500 before the indirection existed).
    expect(await redirectFrom(() => requireAdmin("/orders"))).toBe("/api/auth/purge");
  });

  it("does not blow up when cookie writes are illegal, which is always, for a page", async () => {
    cookieWritesAllowed = false;
    store.set("admin_access", "A");
    store.set("admin_preauth", "P");
    await expect(redirectFrom(() => requireAdmin("/orders"))).resolves.toBe("/api/auth/purge");
  });
});

describe("requirePreauth — the TOTP-step gate", () => {
  it("hands back the preauth token", async () => {
    store.set("admin_preauth", "PRE");
    await expect(requirePreauth()).resolves.toBe("PRE");
  });

  it("refuses a cookieless visitor", async () => {
    expect(await redirectFrom(() => requirePreauth())).toBe("/login");
  });

  it("sends a fully signed-in visitor to the dashboard — the ceremony is over", async () => {
    store.set("admin_access", "A");
    store.set("admin_refresh", "R");
    expect(await redirectFrom(() => requirePreauth())).toBe("/");
  });

  it("sends the anomaly to the purge handler", async () => {
    store.set("admin_access", "A");
    store.set("admin_preauth", "P");
    expect(await redirectFrom(() => requirePreauth())).toBe("/api/auth/purge");
  });
});

describe("gatePage — /login, /totp and the public invite page", () => {
  it("lets a cookieless visitor see the login form", async () => {
    await expect(gatePage("login", "/login")).resolves.toBeUndefined();
  });

  it("sends a preauth holder from /login to the TOTP step", async () => {
    store.set("admin_preauth", "P");
    expect(await redirectFrom(() => gatePage("login", "/login"))).toBe("/totp");
  });

  it("sends a signed-in visitor from /login to the dashboard", async () => {
    store.set("admin_access", "A");
    expect(await redirectFrom(() => gatePage("login", "/login"))).toBe("/");
  });

  it("lets the public invite page render in every ordinary state", async () => {
    await expect(gatePage("public", "/accept-invite")).resolves.toBeUndefined();
    store.set("admin_preauth", "P");
    await expect(gatePage("public", "/accept-invite")).resolves.toBeUndefined();
    store.clear();
    store.set("admin_access", "A");
    await expect(gatePage("public", "/accept-invite")).resolves.toBeUndefined();
  });

  it("but purges the anomaly even on the public page — no route class opts out", async () => {
    store.set("admin_access", "A");
    store.set("admin_preauth", "P");
    expect(await redirectFrom(() => gatePage("public", "/accept-invite"))).toBe(
      "/api/auth/purge",
    );
  });
});

describe("fetchWithAuth", () => {
  it("reads admin_access and refreshes once on a 401, persisting the rotation", async () => {
    store.set("admin_access", "OLD");
    store.set("admin_refresh", "R");
    global.fetch = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/auth/token/refresh/")) {
        return Promise.resolve(
          new Response(JSON.stringify({ access: "NEW", refresh: "R2" }), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
        );
      }
      if (new Headers(init?.headers).get("Authorization") === "Bearer OLD") {
        return Promise.resolve(new Response("{}", { status: 401 }));
      }
      return Promise.resolve(
        new Response(JSON.stringify({ email: "a@b.com" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    }) as unknown as typeof fetch;

    await expect(fetchWithAuth<{ email: string }>("/auth/admin-me/")).resolves.toEqual({
      email: "a@b.com",
    });
    expect(setSpy).toHaveBeenCalledWith("admin_access", "NEW");
    expect(setSpy).toHaveBeenCalledWith("admin_refresh", "R2");
  });

  it("NEVER falls back to the preauth cookie", async () => {
    store.set("admin_preauth", "PREAUTH");
    const fetchSpy = vi.fn(() =>
      Promise.resolve(new Response("{}", { status: 401 })),
    );
    global.fetch = fetchSpy as unknown as typeof fetch;

    await expect(fetchWithAuth("/auth/admin-me/")).rejects.toThrow();
    const init = (fetchSpy.mock.calls[0] as unknown[])[1] as RequestInit | undefined;
    expect(new Headers(init?.headers).get("Authorization")).toBeNull();
  });

  it("trips the RSC write probe rather than blacklisting a refresh token it cannot store", async () => {
    cookieWritesAllowed = false;
    await expect(fetchWithAuth("/auth/admin-me/")).rejects.toBeInstanceOf(RscCookieWriteError);
  });
});

describe("fetchWithAuthOrBounce — the Server Component fetcher", () => {
  it("decides the bounce up front when there is no access token, without calling the API", async () => {
    store.set("admin_refresh", "R");
    const fetchSpy = vi.fn(() => Promise.resolve(new Response("{}")));
    global.fetch = fetchSpy as unknown as typeof fetch;

    expect(await redirectFrom(() => fetchWithAuthOrBounce("/auth/admin-me/", "/orders"))).toBe(
      `/api/auth/refresh-redirect?next=${encodeURIComponent("/orders")}`,
    );
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("bounces to /login on a 401 when there is nothing left to renew with", async () => {
    store.set("admin_access", "DEAD");
    global.fetch = vi.fn(() =>
      Promise.resolve(new Response("{}", { status: 401 })),
    ) as unknown as typeof fetch;

    expect(await redirectFrom(() => fetchWithAuthOrBounce("/auth/admin-me/", "/orders"))).toBe(
      `/login?next=${encodeURIComponent("/orders")}`,
    );
  });

  it("never writes a cookie, so it is safe from a Server Component", async () => {
    cookieWritesAllowed = false;
    store.set("admin_access", "A");
    global.fetch = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    ) as unknown as typeof fetch;

    await expect(fetchWithAuthOrBounce("/auth/admin-me/", "/")).resolves.toEqual({ ok: true });
  });
});
