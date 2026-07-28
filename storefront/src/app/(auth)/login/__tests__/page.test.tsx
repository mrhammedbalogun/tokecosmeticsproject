import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const store = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: () => undefined,
    delete: (n: string) => store.delete(n),
  }),
}));

class Redirected extends Error {
  constructor(public to: string) { super(`NEXT_REDIRECT ${to}`); }
}
vi.mock("next/navigation", () => ({
  redirect: (to: string) => { throw new Redirected(to); },
}));

import LoginPage from "../page";

beforeEach(() => { store.clear(); });
afterEach(() => { vi.restoreAllMocks(); });

function visit(next?: string | string[]) {
  return LoginPage({ searchParams: Promise.resolve(next === undefined ? {} : { next }) });
}

describe("login page entry states", () => {
  it("renders the form for a visitor with no session", async () => {
    await expect(visit("/account/orders")).resolves.toBeTruthy();
  });

  it("skips the form when both session cookies are present", async () => {
    store.set("access", "AAA");
    store.set("refresh", "RRR");
    await expect(visit("/account/orders")).rejects.toThrow("NEXT_REDIRECT /account/orders");
  });

  it("renews rather than asking for a password when only the refresh survives", async () => {
    store.set("refresh", "RRR");
    await expect(visit("/account/orders")).rejects.toThrow(
      "NEXT_REDIRECT /api/auth/refresh-redirect?next=%2Faccount%2Forders",
    );
  });

  it("shows the form for an access cookie with no refresh, instead of looping", async () => {
    // proxy.ts:40 bounces /account* to /login whenever the refresh cookie is absent, so
    // redirecting this visitor onward would return them here immediately, forever.
    store.set("access", "AAA");
    await expect(visit("/account")).resolves.toBeTruthy();
  });

  it("refuses an off-site destination on the short-circuit", async () => {
    store.set("access", "AAA");
    store.set("refresh", "RRR");
    await expect(visit("https://evil.example/pwn")).rejects.toThrow("NEXT_REDIRECT /account");
  });

  it("survives a repeated next param instead of 500ing", async () => {
    // `?next=/a&next=/b` arrives as string[]; safeNext would call charCodeAt on the array.
    store.set("access", "AAA");
    store.set("refresh", "RRR");
    await expect(visit(["/account/orders", "//evil.example"])).rejects.toThrow(
      "NEXT_REDIRECT /account/orders",
    );
  });

  it("does not index itself", async () => {
    const { metadata } = await import("../page");
    expect(metadata.robots).toMatchObject({ index: false });
  });
});
