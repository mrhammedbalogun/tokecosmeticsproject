import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const store = new Map<string, string>([["country", "NG"]]);
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
  }),
}));

import { GET as storesGET } from "@/app/api/stores/route";
import { GET as placesGET } from "@/app/api/stores/places/route";

/**
 * The two locator proxies cache DIFFERENTLY on purpose, and that asymmetry is the thing
 * most likely to be "tidied" into a bug later.
 *
 * `/api/stores/places` returns the cascade — names and counts, no phone numbers — so it
 * is identical for every market and may sit in a shared cache. `/api/stores` returns
 * store cards whose phone numbers are formatted against the reader's market (X-Country,
 * from a cookie), so the same URL has different bodies for different visitors and must
 * NOT carry a public Cache-Control. Both may use the data cache, because Next hashes
 * request headers into the fetch cache key.
 */

const originalFetch = global.fetch;
beforeEach(() => { process.env.API_URL = "http://backend:8000"; store.set("country", "NG"); });
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function upstream(body: unknown, status = 200) {
  const f = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  );
  global.fetch = f as unknown as typeof fetch;
  return f;
}

const sReq = (qs: string) => new Request(`https://shop.test/api/stores${qs}`);
const pReq = (qs: string) => new Request(`https://shop.test/api/stores/places${qs}`);

const nextOf = (f: ReturnType<typeof upstream>, i = 0) =>
  (f.mock.calls[i][1] as { next?: { revalidate?: number; tags?: string[] } }).next;

describe("/api/stores/places — publicly cacheable", () => {
  it("returns the cascade with shared-cache directives", async () => {
    upstream({ level: "state", items: [{ slug: "lagos", name: "Lagos", store_count: 3 }] });
    const res = await placesGET(pReq("?country=NG"));

    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe(
      "public, s-maxage=300, stale-while-revalidate=300",
    );
    expect(await res.json()).toEqual({
      level: "state",
      items: [{ slug: "lagos", name: "Lagos", store_count: 3 }],
    });
  });

  it("revalidates the upstream fetch at 300s under the flushable 'stores' tag", async () => {
    const f = upstream({});
    await placesGET(pReq("?country=NG"));

    expect(nextOf(f)?.revalidate).toBe(300);
    expect(nextOf(f)?.tags).toContain("stores");
    expect((f.mock.calls[0][1] as { cache?: string }).cache).toBeUndefined();
  });

  it("keys on country and state, so one level cannot be served for another", async () => {
    const a = upstream({});
    await placesGET(pReq("?country=NG"));
    expect(String(a.mock.calls[0][0])).toContain("/stores/places/?country=NG");

    const b = upstream({});
    await placesGET(pReq("?country=NG&state=lagos"));
    expect(String(b.mock.calls[0][0])).toContain("country=NG&state=lagos");

    const c = upstream({});
    await placesGET(pReq(""));
    expect(String(c.mock.calls[0][0])).toContain("/stores/places/");
  });
});

describe("/api/stores — data cache only, never a shared one", () => {
  it("does NOT return a public Cache-Control, because the body varies by market", async () => {
    upstream({ results: [{ phone_display: "0707 480 0702" }] });
    const res = await storesGET(sReq("?country=NG"));

    expect(res.status).toBe(200);
    // The guard. A public header here would let one visitor's phone formatting be
    // served to another — see apps/core/phones.py::format_display.
    expect(res.headers.get("cache-control")).toBeNull();
  });

  it("still revalidates upstream at 300s under the 'stores' tag", async () => {
    const f = upstream({});
    await storesGET(sReq("?country=NG"));

    expect(nextOf(f)?.revalidate).toBe(300);
    expect(nextOf(f)?.tags).toContain("stores");
    expect((f.mock.calls[0][1] as { cache?: string }).cache).toBeUndefined();
  });

  it("carries the reader's market as X-Country — the input the data-cache key hashes", async () => {
    const ng = upstream({});
    await storesGET(sReq("?country=NG"));
    expect(new Headers((ng.mock.calls[0][1] as RequestInit).headers).get("X-Country")).toBe("NG");

    store.set("country", "GB");
    const gb = upstream({});
    await storesGET(sReq("?country=NG"));
    // Same URL, different X-Country: distinct data-cache entries, distinct bodies.
    expect(new Headers((gb.mock.calls[0][1] as RequestInit).headers).get("X-Country")).toBe("GB");
  });

  it("keys on country, state, area and page", async () => {
    const f = upstream({});
    await storesGET(sReq("?country=NG&state=lagos&area=ikeja&page=2"));
    const sent = String(f.mock.calls[0][0]);
    expect(sent).toContain("country=NG");
    expect(sent).toContain("state=lagos");
    expect(sent).toContain("area=ikeja");
    expect(sent).toContain("page=2");
  });

  it("drops a non-numeric page rather than forwarding it into the cache key", async () => {
    const f = upstream({});
    await storesGET(sReq("?country=NG&page=../../etc"));
    expect(String(f.mock.calls[0][0])).not.toContain("page=");
  });

  it("forwards no Authorization or cookie header — the locator is anonymous for everyone", async () => {
    const f = upstream({});
    await storesGET(sReq("?country=NG"));
    const h = new Headers((f.mock.calls[0][1] as RequestInit).headers);
    expect(h.get("authorization")).toBeNull();
    expect(h.get("cookie")).toBeNull();
  });
});

describe("failures stay uncached on both routes", () => {
  it("/api/stores/places passes an upstream 522 through with no Cache-Control", async () => {
    upstream({ detail: "Connection timed out" }, 522);
    const res = await placesGET(pReq("?country=NG"));
    expect(res.status).toBe(522);
    expect(res.headers.get("cache-control")).toBeNull();
  });

  it("/api/stores maps a network failure to 502, uncached", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("socket hang up")) as unknown as typeof fetch;
    const res = await storesGET(sReq("?country=NG"));
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ detail: "Unexpected error." });
    expect(res.headers.get("cache-control")).toBeNull();
  });

  it("/api/stores still refuses a request with no country, and does not call upstream", async () => {
    const f = upstream({});
    const res = await storesGET(sReq(""));
    expect(res.status).toBe(400);
    expect(res.headers.get("cache-control")).toBeNull();
    expect(f).not.toHaveBeenCalled();
  });
});
