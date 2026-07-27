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

import RegisterPage from "../page";

beforeEach(() => { store.clear(); });
afterEach(() => { vi.restoreAllMocks(); });

function visit(next?: string | string[]) {
  return RegisterPage({ searchParams: Promise.resolve(next === undefined ? {} : { next }) });
}

describe("register page entry states", () => {
  it("renders the form for a visitor with no session", async () => {
    await expect(visit("/account")).resolves.toBeTruthy();
  });

  it("sends an already-signed-in visitor to their destination", async () => {
    store.set("access", "AAA");
    store.set("refresh", "RRR");
    await expect(visit("/cart")).rejects.toThrow("NEXT_REDIRECT /cart");
  });

  it("renews rather than showing a signup form when only the refresh survives", async () => {
    store.set("refresh", "RRR");
    await expect(visit("/account")).rejects.toThrow(
      "NEXT_REDIRECT /api/auth/refresh-redirect?next=%2Faccount",
    );
  });

  it("renders the form for an access cookie with no refresh, instead of looping", async () => {
    store.set("access", "AAA");
    await expect(visit("/account")).resolves.toBeTruthy();
  });

  it("refuses an off-site destination", async () => {
    store.set("access", "AAA");
    store.set("refresh", "RRR");
    await expect(visit("https://evil.example")).rejects.toThrow("NEXT_REDIRECT /account");
  });

  it("survives a repeated next param", async () => {
    store.set("access", "AAA");
    store.set("refresh", "RRR");
    await expect(visit(["/cart", "//evil.example"])).rejects.toThrow("NEXT_REDIRECT /cart");
  });

  it("does not index itself", async () => {
    const { metadata } = await import("../page");
    expect(metadata.robots).toMatchObject({ index: false });
  });
});
