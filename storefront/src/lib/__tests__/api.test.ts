import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiFetch, ApiError } from "@/lib/api";

const originalFetch = global.fetch;

beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

function mockFetch(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
  global.fetch = f as unknown as typeof fetch;
  return f;
}

describe("apiFetch", () => {
  it("prefixes API_URL and the /api/v1 path", async () => {
    const f = mockFetch(200, { ok: true });
    await apiFetch("/meta/countries/");
    expect(f).toHaveBeenCalledOnce();
    const url = f.mock.calls[0][0] as string;
    expect(url).toBe("http://backend:8000/api/v1/meta/countries/");
  });

  it("sends X-Country from the option (default NG)", async () => {
    const f = mockFetch(200, {});
    await apiFetch("/cart/", { country: "GB" });
    const init = f.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("X-Country")).toBe("GB");

    await apiFetch("/cart/");
    const init2 = (f.mock.calls[1][1] as RequestInit);
    expect(new Headers(init2.headers).get("X-Country")).toBe("NG");
  });

  it("adds a Bearer header when a token is given", async () => {
    const f = mockFetch(200, {});
    await apiFetch("/auth/me/", { token: "abc.def.ghi" });
    const init = f.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer abc.def.ghi");
  });

  it("returns parsed JSON on success", async () => {
    mockFetch(200, { code: "NG" });
    const data = await apiFetch<{ code: string }>("/meta/countries/");
    expect(data.code).toBe("NG");
  });

  it("throws ApiError with status + parsed body on 4xx", async () => {
    mockFetch(400, { email: ["Account already exists"] });
    await expect(apiFetch("/auth/register/", { method: "POST", body: {} })).rejects.toMatchObject({
      status: 400,
      data: { email: ["Account already exists"] },
    });
  });

  it("does not send a Bearer header when no token", async () => {
    const f = mockFetch(200, {});
    await apiFetch("/meta/countries/");
    const init = f.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get("Authorization")).toBeNull();
  });
});
