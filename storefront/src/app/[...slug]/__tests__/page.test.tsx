import { afterEach, describe, expect, it, vi } from "vitest";

class Redirected extends Error {
  constructor(public to: string, public permanent: boolean) {
    super(`NEXT_REDIRECT ${to}`);
  }
}
class NotFound extends Error {
  constructor() { super("NEXT_NOT_FOUND"); }
}

vi.mock("next/navigation", () => ({
  redirect: (to: string) => { throw new Redirected(to, false); },
  permanentRedirect: (to: string) => { throw new Redirected(to, true); },
  notFound: () => { throw new NotFound(); },
}));

const getRedirect = vi.fn();
vi.mock("@/lib/redirects", () => ({ getRedirect: (p: string) => getRedirect(p) }));

import CatchAll from "../page";

afterEach(() => { vi.clearAllMocks(); });

function visit(...segments: string[]) {
  return CatchAll({ params: Promise.resolve({ slug: segments }) });
}

describe("the legacy URL catch-all", () => {
  it("REDIRECTS A KNOWN LEGACY URL PERMANENTLY", async () => {
    getRedirect.mockResolvedValue({
      old_path: "/our-story", new_path: "/page/our-story", status_code: 301,
    });

    const err = await visit("our-story").catch((e) => e);

    expect(err).toBeInstanceOf(Redirected);
    expect(err.to).toBe("/page/our-story");
    expect(err.permanent).toBe(true);
  });

  it("uses a temporary redirect for a 302 row", async () => {
    getRedirect.mockResolvedValue({
      old_path: "/x", new_path: "/y", status_code: 302,
    });

    const err = await visit("x").catch((e) => e);

    expect(err).toBeInstanceOf(Redirected);
    expect(err.permanent).toBe(false);
  });

  it("404s an unknown path", async () => {
    getRedirect.mockResolvedValue(null);
    await expect(visit("never-existed")).rejects.toBeInstanceOf(NotFound);
  });

  it("RENDERS NOT-FOUND FOR A 410 ROW rather than redirecting somewhere invented", async () => {
    // A Server Component cannot set an arbitrary status, so a 410 row answers 404. What
    // matters is that it does NOT become a redirect to the homepage — that would tell
    // Google the content moved there, which is false.
    getRedirect.mockResolvedValue({
      old_path: "/home-2-duplicate-5203", new_path: "", status_code: 410,
    });

    await expect(visit("home-2-duplicate-5203")).rejects.toBeInstanceOf(NotFound);
  });

  it("passes the full path for a nested legacy URL", async () => {
    getRedirect.mockResolvedValue(null);
    await visit("product-category", "skin-care").catch(() => undefined);
    expect(getRedirect).toHaveBeenCalledWith("/product-category/skin-care");
  });

  it("handles the empty segment list without throwing on undefined", async () => {
    getRedirect.mockResolvedValue(null);
    await visit().catch(() => undefined);
    expect(getRedirect).toHaveBeenCalledWith("/");
  });
});
