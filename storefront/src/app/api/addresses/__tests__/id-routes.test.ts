import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Same next/headers cookie-store mock as checkout/__tests__/buy-now.test.ts.
const store = new Map<string, string>([["access", "TOK"], ["country", "NG"]]);
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

import { PATCH, DELETE } from "@/app/api/addresses/[id]/route";
import { POST } from "@/app/api/addresses/[id]/default/route";

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.set("access", "TOK");
  store.set("country", "NG");
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

function upstream(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(
    new Response(body === null ? null : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
  global.fetch = f as unknown as typeof fetch;
  return f;
}

const params = (id: string) => Promise.resolve({ id });

const patchReq = (body: unknown) =>
  new Request("http://localhost:3000/api/addresses/12", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
const deleteReq = () =>
  new Request("http://localhost:3000/api/addresses/12", { method: "DELETE" });
const postReq = (body: unknown) =>
  new Request("http://localhost:3000/api/addresses/12/default", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });

const BAD_IDS = ["12abc", "", "1".repeat(11)];

describe("addresses [id] BFF — PATCH", () => {
  it("forwards body + Bearer + country to /me/addresses/12/ and returns upstream JSON", async () => {
    const f = upstream(200, { id: 12, line1: "New Line" });
    const res = await PATCH(patchReq({ line1: "New Line" }), { params: params("12") });
    expect(res.status).toBe(200);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://backend:8000/api/v1/me/addresses/12/");
    const h = new Headers((init as RequestInit).headers);
    expect(h.get("Authorization")).toBe("Bearer TOK");
    expect(h.get("X-Country")).toBe("NG");
    expect((init as RequestInit).method).toBe("PATCH");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ line1: "New Line" });
    expect(await res.json()).toEqual({ id: 12, line1: "New Line" });
  });

  it("passes a 400 upstream field-error body and status through", async () => {
    upstream(400, { line1: ["This field is required."] });
    const res = await PATCH(patchReq({ line1: "" }), { params: params("12") });
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ line1: ["This field is required."] });
  });

  it("passes a stranger's-address 404 through", async () => {
    upstream(404, { detail: "Not found." });
    const res = await PATCH(patchReq({ line1: "x" }), { params: params("12") });
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ detail: "Not found." });
  });

  it.each(BAD_IDS)("id %j -> 404, upstream never called", async (id) => {
    const f = upstream(200, {});
    const res = await PATCH(patchReq({ line1: "x" }), { params: params(id) });
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ detail: "Not found." });
    expect(f).not.toHaveBeenCalled();
  });

  it("401 without a session, no upstream call", async () => {
    store.delete("access");
    store.delete("refresh");
    const f = upstream(200, {});
    const res = await PATCH(patchReq({ line1: "x" }), { params: params("12") });
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({ detail: "Not authenticated." });
    expect(f).not.toHaveBeenCalled();
  });
});

describe("addresses [id] BFF — DELETE", () => {
  it("returns 204 with an empty body", async () => {
    const f = upstream(204, null);
    const res = await DELETE(deleteReq(), { params: params("12") });
    expect(res.status).toBe(204);
    expect(await res.text()).toBe("");
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://backend:8000/api/v1/me/addresses/12/");
    expect((init as RequestInit).method).toBe("DELETE");
  });

  it("passes a stranger's-address 404 through", async () => {
    upstream(404, { detail: "Not found." });
    const res = await DELETE(deleteReq(), { params: params("12") });
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ detail: "Not found." });
  });

  it.each(BAD_IDS)("id %j -> 404, upstream never called", async (id) => {
    const f = upstream(204, null);
    const res = await DELETE(deleteReq(), { params: params(id) });
    expect(res.status).toBe(404);
    expect(f).not.toHaveBeenCalled();
  });

  it("401 without a session, no upstream call", async () => {
    store.delete("access");
    store.delete("refresh");
    const f = upstream(204, null);
    const res = await DELETE(deleteReq(), { params: params("12") });
    expect(res.status).toBe(401);
    expect(f).not.toHaveBeenCalled();
  });
});

describe("addresses [id]/default BFF — POST", () => {
  it("kind=shipping hits /me/addresses/12/set-default-shipping/", async () => {
    const f = upstream(200, { id: 12, is_default_shipping: true });
    const res = await POST(postReq({ kind: "shipping" }), { params: params("12") });
    expect(res.status).toBe(200);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("http://backend:8000/api/v1/me/addresses/12/set-default-shipping/");
    expect((init as RequestInit).method).toBe("POST");
    expect(await res.json()).toEqual({ id: 12, is_default_shipping: true });
  });

  it("kind=billing hits /me/addresses/12/set-default-billing/", async () => {
    const f = upstream(200, { id: 12, is_default_billing: true });
    const res = await POST(postReq({ kind: "billing" }), { params: params("12") });
    expect(res.status).toBe(200);
    expect(f.mock.calls[0][0]).toBe(
      "http://backend:8000/api/v1/me/addresses/12/set-default-billing/",
    );
  });

  it("passes a stranger's-address 404 through", async () => {
    upstream(404, { detail: "Not found." });
    const res = await POST(postReq({ kind: "shipping" }), { params: params("12") });
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({ detail: "Not found." });
  });

  it.each([["missing", {}], ["uppercase", { kind: "SHIPPING" }], ["garbage", { kind: "x" }]] as const)(
    "kind %s -> 400, upstream never called",
    async (_label, body) => {
      const f = upstream(200, {});
      const res = await POST(postReq(body), { params: params("12") });
      expect(res.status).toBe(400);
      expect(await res.json()).toEqual({ detail: "Invalid kind." });
      expect(f).not.toHaveBeenCalled();
    },
  );

  it.each(BAD_IDS)("id %j -> 404, upstream never called", async (id) => {
    const f = upstream(200, {});
    const res = await POST(postReq({ kind: "shipping" }), { params: params(id) });
    expect(res.status).toBe(404);
    expect(f).not.toHaveBeenCalled();
  });

  it("401 without a session, no upstream call", async () => {
    store.delete("access");
    store.delete("refresh");
    const f = upstream(200, {});
    const res = await POST(postReq({ kind: "shipping" }), { params: params("12") });
    expect(res.status).toBe(401);
    expect(f).not.toHaveBeenCalled();
  });
});
