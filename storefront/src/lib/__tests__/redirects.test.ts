import { afterEach, describe, expect, it, vi } from "vitest";

// vi.mock is hoisted above the file body, so the error class has to be hoisted with it.
const { apiFetch, ApiError } = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  ApiError: class ApiError extends Error {
    constructor(public status: number) { super(`api ${status}`); }
  },
}));
vi.mock("@/lib/api", () => ({ apiFetch, ApiError }));

import { getRedirect } from "../redirects";

afterEach(() => { vi.clearAllMocks(); });

describe("getRedirect", () => {
  it("returns the rule", async () => {
    apiFetch.mockResolvedValue({ old_path: "/a", new_path: "/b", status_code: 301 });
    expect(await getRedirect("/a")).toEqual({
      old_path: "/a", new_path: "/b", status_code: 301,
    });
  });

  it("encodes the path so a query string cannot escape the parameter", async () => {
    apiFetch.mockResolvedValue(null);
    await getRedirect("/a?b=c&d=e");
    expect(apiFetch).toHaveBeenCalledWith(
      "/meta/redirect/?path=%2Fa%3Fb%3Dc%26d%3De",
      expect.anything(),
    );
  });

  it("returns null on a 404", async () => {
    apiFetch.mockRejectedValue(new ApiError(404));
    expect(await getRedirect("/nope")).toBeNull();
  });

  it("A BACKEND OUTAGE GIVES THE 404 PAGE, NOT A 500", async () => {
    // The visitor was heading for a 404 anyway. This lookup is a chance to do better,
    // never a reason to do worse.
    apiFetch.mockRejectedValue(new Error("ECONNREFUSED"));
    expect(await getRedirect("/anything")).toBeNull();
  });

  it("caches for an hour under the redirects tag", async () => {
    apiFetch.mockResolvedValue(null);
    await getRedirect("/a");
    expect(apiFetch).toHaveBeenCalledWith(expect.any(String), {
      next: { revalidate: 3600, tags: ["redirects"] },
    });
  });
});
