import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiFetchRaw } from "@/lib/api";

/**
 * The multipart branch of `apiFetchRaw`, added in Plan-17a Task 5 for the one endpoint
 * that takes a file (`POST /admin/products/{slug}/images/`).
 *
 * Worth its own test because the failure is invisible from the client: a hand-set
 * `Content-Type: multipart/form-data` carries no boundary token, Django parses an empty
 * payload, and the response is "No file was submitted" for a request that plainly
 * contains one. Only fetch knows the boundary, so only fetch may write that header.
 */
describe("apiFetchRaw with FormData", () => {
  const original = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
  });
  afterEach(() => {
    global.fetch = original;
  });

  const init = () => (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1] as RequestInit;

  it("passes the FormData through untouched", async () => {
    const body = new FormData();
    body.append("image", new File(["x"], "a.png", { type: "image/png" }));

    await apiFetchRaw("/admin/products/p/images/", { method: "POST", body });

    expect(init().body).toBe(body);
  });

  it("DOES NOT set Content-Type, so fetch can generate one with a boundary", () => {
    const body = new FormData();
    body.append("image", new File(["x"], "a.png", { type: "image/png" }));

    return apiFetchRaw("/admin/products/p/images/", { method: "POST", body }).then(() => {
      const headers = init().headers as Headers;
      expect(headers.get("Content-Type")).toBeNull();
    });
  });

  it("still JSON-encodes an ordinary object body", async () => {
    await apiFetchRaw("/admin/images/1/", { method: "PATCH", body: { alt: "swatch" } });

    const headers = init().headers as Headers;
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init().body).toBe(JSON.stringify({ alt: "swatch" }));
  });

  it("sends no body at all when none was given", async () => {
    await apiFetchRaw("/admin/products/", {});

    expect(init().body).toBeUndefined();
    expect((init().headers as Headers).get("Content-Type")).toBeNull();
  });

  it("still carries the bearer token on a multipart request", async () => {
    // The upload is authenticated like everything else; losing the header here would fail
    // as a 401 that looks like a session problem rather than a request-shape one.
    const body = new FormData();
    body.append("image", new File(["x"], "a.png", { type: "image/png" }));

    await apiFetchRaw("/admin/products/p/images/", { method: "POST", body, token: "tok" });

    expect((init().headers as Headers).get("Authorization")).toBe("Bearer tok");
  });
});
