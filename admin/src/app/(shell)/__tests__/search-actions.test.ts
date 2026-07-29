import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

/** `redirect()` throws NEXT_REDIRECT in production. Mocked so that a search action which
 *  ever grew one would be visible here as a thrown error rather than silently working. */
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`unexpected redirect to ${to}`);
  },
}));

import { searchAction } from "../search-actions";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.clear();
  store.set("admin_access", "ACCESS");
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

describe("searchAction", () => {
  it("calls the admin search endpoint with the bearer token and the encoded term", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ orders: [], customers: [] }));
    global.fetch = fetchMock as unknown as typeof fetch;

    const state = await searchAction("  a+b@x.com  ");

    expect(state.query).toBe("a+b@x.com");
    expect(state.results).toEqual({ orders: [], customers: [] });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://backend:8000/api/v1/admin/search/?q=a%2Bb%40x.com");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer ACCESS");
  });

  it("does not call the API at all below the minimum length", async () => {
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    expect(await searchAction("ab")).toEqual({ query: "ab", results: null });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("passes through only the sections the backend returned", async () => {
    // The Support case: no `products` key at all, because that section is behind
    // `products.manage`. Nothing in this app re-decides that — it renders what it is given.
    global.fetch = vi.fn(async () =>
      jsonResponse({ orders: [{ number: "TC-1" }], customers: [] }),
    ) as unknown as typeof fetch;

    const state = await searchAction("zeta");

    expect(Object.keys(state.results!)).toEqual(["orders", "customers"]);
  });

  it("surfaces a throttled search as a message instead of throwing", async () => {
    global.fetch = vi.fn(async () =>
      jsonResponse({ detail: "Request was throttled." }, 429),
    ) as unknown as typeof fetch;

    const state = await searchAction("zeta");

    expect(state.results).toBeNull();
    expect(state.error).toMatch(/too many/i);
  });

  it("does not redirect when the session is gone — it reports it", async () => {
    // The property under test: this runs on every debounced keystroke, so a redirect here
    // would yank a staff member off the page mid-word the moment their token expired.
    // There is no refresh cookie in the jar, so `fetchWithAuth` cannot renew and the 401
    // reaches the action.
    global.fetch = vi.fn(async () => jsonResponse({ detail: "no" }, 401)) as unknown as typeof fetch;

    const state = await searchAction("zeta");

    expect(state.results).toBeNull();
    expect(state.error).toMatch(/session/i);
  });

  it("renews once and retries when the access token has expired", async () => {
    store.set("admin_refresh", "REFRESH");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: "expired" }, 401))
      .mockResolvedValueOnce(jsonResponse({ access: "NEW", refresh: "NEWREF" }))
      .mockResolvedValueOnce(jsonResponse({ orders: [] }));
    global.fetch = fetchMock as unknown as typeof fetch;

    const state = await searchAction("zeta");

    expect(state.results).toEqual({ orders: [] });
    expect(store.get("admin_access")).toBe("NEW");
    const [lastUrl, lastInit] = fetchMock.mock.calls[2] as unknown as [string, RequestInit];
    expect(lastUrl).toContain("/admin/search/");
    expect(new Headers(lastInit.headers).get("Authorization")).toBe("Bearer NEW");
  });
});
