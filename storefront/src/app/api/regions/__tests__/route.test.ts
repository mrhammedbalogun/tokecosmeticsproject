import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { GET } from "@/app/api/regions/route";

/**
 * The regions proxy is public reference data — administrative geography — so it is the
 * one BFF route in this app that may be held in a SHARED cache. These tests pin the
 * three things that makes safe: the cache directives, the per-input cache key, and the
 * rule that a failure is never cached (the Django origin answers 522 intermittently).
 */

const CACHE_CONTROL = "public, s-maxage=86400, stale-while-revalidate=86400";
const originalFetch = global.fetch;

beforeEach(() => { process.env.API_URL = "http://backend:8000"; });
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

/** Captures the (url, init) the route hands to fetch, so the cache options are assertable. */
function upstream(body: unknown, status = 200) {
  const f = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  );
  global.fetch = f as unknown as typeof fetch;
  return f;
}

const req = (qs: string) => new Request(`https://shop.test/api/regions${qs}`);

describe("GET /api/regions — caching", () => {
  it("returns the upstream JSON unchanged, with public shared-cache directives", async () => {
    upstream([{ id: 1, name: "Lagos", level: "state", has_children: true }]);
    const res = await GET(req("?country=NG"));

    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe(CACHE_CONTROL);
    expect(res.headers.get("content-type")).toBe("application/json");
    expect(await res.json()).toEqual([
      { id: 1, name: "Lagos", level: "state", has_children: true },
    ]);
  });

  it("asks Next to revalidate the upstream fetch every 86400s, under a flushable tag", async () => {
    const f = upstream([]);
    await GET(req("?country=NG"));

    const init = f.mock.calls[0][1] as { next?: { revalidate?: number; tags?: string[] } };
    expect(init.next?.revalidate).toBe(86400);
    expect(init.next?.tags).toContain("regions");
    // The old `no-store` must be gone, or the revalidate above is dead letter.
    expect((init as { cache?: string }).cache).toBeUndefined();
  });

  it("exposes no session data: no cookie, no auth header goes upstream", async () => {
    const f = upstream([]);
    await GET(req("?country=NG"));

    const headers = new Headers((f.mock.calls[0][1] as RequestInit).headers);
    expect(headers.get("authorization")).toBeNull();
    expect(headers.get("cookie")).toBeNull();
  });
});

describe("GET /api/regions — cache key", () => {
  it("keys on ?country=, so one country's states cannot be served for another", async () => {
    const ng = upstream([]);
    await GET(req("?country=NG"));
    expect(String(ng.mock.calls[0][0])).toContain("/meta/regions/?country=NG");

    const gb = upstream([]);
    await GET(req("?country=GB"));
    expect(String(gb.mock.calls[0][0])).toContain("/meta/regions/?country=GB");
  });

  it("keys on ?parent= for the LGA level", async () => {
    const f = upstream([]);
    await GET(req("?parent=12"));
    expect(String(f.mock.calls[0][0])).toContain("/meta/regions/?parent=12");
  });

  it("encodes the parameter, so a crafted value cannot alter the upstream query", async () => {
    const f = upstream([]);
    await GET(req("?country=NG%26parent=99"));
    expect(String(f.mock.calls[0][0])).toContain("country=NG%26parent%3D99");
  });
});

describe("GET /api/regions — error handling is unchanged and uncached", () => {
  it("passes an upstream status through and attaches NO Cache-Control", async () => {
    // The real case: Cloudflare 522 between the edge and the VPS. Caching that for a day
    // would empty the State dropdown for every shopper until it expired.
    upstream({ detail: "Connection timed out" }, 522);
    const res = await GET(req("?country=NG"));

    expect(res.status).toBe(522);
    expect(res.headers.get("cache-control")).toBeNull();
  });

  it("maps a non-ApiError failure to 500, still uncached", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("socket hang up")) as unknown as typeof fetch;
    const res = await GET(req("?country=NG"));

    expect(res.status).toBe(500);
    expect(await res.json()).toEqual({ detail: "Unexpected error." });
    expect(res.headers.get("cache-control")).toBeNull();
  });

  it("still rejects a request naming neither parameter, and does not cache that either", async () => {
    const f = upstream([]);
    const res = await GET(req(""));

    expect(res.status).toBe(400);
    expect(res.headers.get("cache-control")).toBeNull();
    expect(f).not.toHaveBeenCalled();
  });
});
