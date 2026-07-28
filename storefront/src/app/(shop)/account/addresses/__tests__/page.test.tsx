import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { Address } from "@/components/checkout/address-fields";

const store = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (n: string) => (store.has(n) ? { name: n, value: store.get(n) } : undefined),
    set: (n: string, v: string) => store.set(n, v),
    delete: (n: string) => store.delete(n),
  }),
}));

class Redirected extends Error {
  constructor(public to: string) { super(`NEXT_REDIRECT ${to}`); }
}
vi.mock("next/navigation", () => ({
  redirect: (to: string) => { throw new Redirected(to); },
}));

import AddressesPage from "../page";

const ADDRESSES: Address[] = [
  {
    id: 1, label: "Home", first_name: "Ada", phone: "0700", line1: "1 Baker St",
    country_code: "GB", city_text: "London", postcode: "NW1",
    is_default_shipping: true, is_default_billing: true,
  },
];

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.clear();
  store.set("access", "AAA");
  store.set("refresh", "RRR");
  global.fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(ADDRESSES), {
      status: 200, headers: { "content-type": "application/json" },
    }),
  ) as unknown as typeof fetch;
});
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

describe("addresses page", () => {
  it("fetches /me/addresses/ and hands the list to AddressBook", async () => {
    render(await AddressesPage());

    expect(screen.getByRole("heading", { name: /addresses/i })).toBeInTheDocument();
    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.getByText(/1 Baker St/)).toBeInTheDocument();
  });

  it("bounces to /account/addresses (not /account) on a stale session with no refresh cookie", async () => {
    store.delete("access");
    store.delete("refresh");
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Not authenticated." }), {
        status: 401, headers: { "content-type": "application/json" },
      }),
    ) as unknown as typeof fetch;

    await expect(AddressesPage()).rejects.toThrow("NEXT_REDIRECT /login?next=%2Faccount%2Faddresses");
  });
});
