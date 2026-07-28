import { describe, it, expect, vi, beforeEach } from "vitest";

// `@/lib/session` is mocked rather than `global.fetch`: this route's whole contract is
// the mapping from an upstream Response to ours, and only owning the Response object
// lets us assert its body was RELEASED. fetchWithAuthRaw's own refresh-and-retry
// behaviour is covered in src/lib/__tests__/session.test.ts.
const { rawFetch } = vi.hoisted(() => ({ rawFetch: vi.fn() }));
vi.mock("@/lib/session", () => ({ fetchWithAuthRaw: rawFetch }));

import { GET } from "@/app/api/orders/[number]/invoice/route";

const PDF = "%PDF-1.4 pretend-invoice";

/** A real Response over a real stream, with a spy on the stream's `cancel`. */
function upstream(status: number, headers: Record<string, string> = {}, body = PDF) {
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      c.enqueue(new TextEncoder().encode(body));
      c.close();
    },
  });
  const res = new Response(status === 204 || status === 304 ? null : stream, {
    status,
    headers,
  });
  const cancel = vi.spyOn(res.body!, "cancel");
  rawFetch.mockResolvedValue(res);
  return { res, cancel };
}

const call = (number: string) =>
  GET(new Request("http://localhost:3000/api/orders/x/invoice"), {
    params: Promise.resolve({ number }),
  });

beforeEach(() => {
  rawFetch.mockReset();
});

describe("invoice BFF — order-number validation", () => {
  // Next hands `number` back DECODED, so these are post-decode values.
  it.each([
    ["a character outside the allowlist", "TC#1"],
    ["a decoded traversal attempt", "../.."],
    ["a decoded slash", "TC-1/../../etc"],
    ["33 characters", "A".repeat(33)],
    ["empty", ""],
    ["a dot", "TC-1.pdf"],
  ])("404s on %s with no upstream call", async (_label, number) => {
    const res = await call(number);
    expect(res.status).toBe(404);
    expect(await res.text()).toBe("");
    expect(rawFetch).not.toHaveBeenCalled();
  });

  it("accepts the real order-number format", async () => {
    upstream(200);
    expect((await call("TC-100038")).status).toBe(200);
    expect(rawFetch).toHaveBeenCalledWith("/orders/TC-100038/invoice.pdf");
  });

  it("accepts exactly 32 characters", async () => {
    upstream(200);
    expect((await call("A".repeat(32))).status).toBe(200);
  });
});

describe("invoice BFF — 200", () => {
  it("sets all three headers exactly", async () => {
    upstream(200);
    const res = await call("TC-100038");
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("application/pdf");
    expect(res.headers.get("content-disposition")).toBe(
      'attachment; filename="TC-100038.pdf"',
    );
    expect(res.headers.get("cache-control")).toBe("private, no-store");
  });

  it("overrides the upstream's inline disposition", async () => {
    upstream(200, {
      "content-type": "application/pdf",
      "content-disposition": 'inline; filename="TC-100038.pdf"',
    });
    const res = await call("TC-100038");
    expect(res.headers.get("content-disposition")).toBe(
      'attachment; filename="TC-100038.pdf"',
    );
  });

  it("streams the upstream body through untouched", async () => {
    const { res: up, cancel } = upstream(200);
    const res = await call("TC-100038");
    // The same stream instance: proxied, not buffered and re-emitted.
    expect(res.body).toBe(up.body);
    expect(await res.text()).toBe(PDF);
    expect(cancel).not.toHaveBeenCalled();
  });

  it("forwards Content-Length when upstream provides it", async () => {
    upstream(200, { "content-length": "2048" });
    expect((await call("TC-100038")).headers.get("content-length")).toBe("2048");
  });

  it("forwards nothing else from upstream headers", async () => {
    upstream(200, {
      "x-frame-options": "DENY",
      "set-cookie": "sessionid=leak",
      "cache-control": "public, max-age=31536000",
    });
    const res = await call("TC-100038");
    expect(res.headers.get("x-frame-options")).toBeNull();
    expect(res.headers.get("set-cookie")).toBeNull();
    expect(res.headers.get("cache-control")).toBe("private, no-store");
    expect([...res.headers.keys()].sort()).toEqual([
      "cache-control",
      "content-disposition",
      "content-type",
    ]);
  });
});

describe("invoice BFF — upstream failure mapping", () => {
  it("401 redirects to login with the order as ?next=", async () => {
    const { cancel } = upstream(401, {}, '{"detail":"token expired"}');
    const res = await call("TC-100038");
    expect(res.status).toBe(303);
    expect(res.headers.get("location")).toBe("/login?next=/account/orders/TC-100038");
    expect(await res.text()).toBe("");
    expect(cancel).toHaveBeenCalled();
  });

  it("403 collapses to a bare 404", async () => {
    const { cancel } = upstream(403, {}, '{"detail":"Not authenticated."}');
    const res = await call("TC-100038");
    expect(res.status).toBe(404);
    expect(await res.text()).toBe("");
    expect(cancel).toHaveBeenCalled();
  });

  it("404 stays a bare 404", async () => {
    const { cancel } = upstream(404, {}, '{"detail":"Not found."}');
    const res = await call("TC-100038");
    expect(res.status).toBe(404);
    expect(await res.text()).toBe("");
    expect(cancel).toHaveBeenCalled();
  });

  it("500 becomes a 502 and leaks no upstream body", async () => {
    const { cancel } = upstream(500, {}, "Traceback (most recent call last): ...");
    const res = await call("TC-100038");
    expect(res.status).toBe(502);
    expect(await res.text()).toBe("");
    expect(cancel).toHaveBeenCalled();
  });

  it.each([301, 400, 429, 502, 503])("%i becomes a 502", async (status) => {
    const { cancel } = upstream(status, {}, "nope");
    const res = await call("TC-100038");
    expect(res.status).toBe(502);
    expect(cancel).toHaveBeenCalled();
  });
});
