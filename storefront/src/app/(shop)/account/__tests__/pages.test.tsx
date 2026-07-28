import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

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
  usePathname: () => "/account",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

import AccountLayout from "../layout";
import AccountPage from "../page";
import ProfilePage from "../profile/page";
import SecurityPage from "../security/page";

const ME = {
  email: "shopper@example.com", first_name: "Ada", last_name: "L",
  phone: "", marketing_consent: true, toke_id: "TK-000123",
};

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.clear();
  store.set("access", "AAA");
  store.set("refresh", "RRR");
  global.fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(ME), {
      status: 200, headers: { "content-type": "application/json" },
    }),
  ) as unknown as typeof fetch;
});
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

describe("account layout", () => {
  it("shows who is signed in and links the pages that exist — and none that don't", async () => {
    render(await AccountLayout({ children: <p>child-content</p> }));
    expect(screen.getByText(/TK-000123/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /profile/i })).toHaveAttribute(
      "href", "/account/profile",
    );
    expect(screen.getByRole("link", { name: /security/i })).toHaveAttribute(
      "href", "/account/security",
    );
    expect(screen.getByRole("link", { name: /orders/i })).toHaveAttribute(
      "href", "/account/orders",
    );
    expect(screen.getByRole("link", { name: /addresses/i })).toHaveAttribute(
      "href", "/account/addresses",
    );
    // Wishlist is the next 15d task — a visible link to a 404 is worse than no link
    // (the LoginForm learned this rule first).
    expect(screen.queryByRole("link", { name: /wishlist/i })).not.toBeInTheDocument();
    expect(screen.getByText("child-content")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument();
  });
});

describe("account dashboard", () => {
  it("greets the shopper by name", async () => {
    render(await AccountPage());
    expect(screen.getByText(/Ada/)).toBeInTheDocument();
  });
});

describe("profile page", () => {
  it("prefills the form from /auth/me/ and shows the read-only email", async () => {
    render(await ProfilePage());
    expect(screen.getByLabelText(/first name/i)).toHaveValue("Ada");
    expect(screen.getByLabelText(/marketing/i)).toBeChecked();
    // Email is read-only upstream; render it as text, not as an editable field.
    expect(screen.getByText(/shopper@example.com/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^email$/i)).not.toBeInTheDocument();
  });
});

describe("security page", () => {
  it("renders the password form and keeps deletion behind a reveal", async () => {
    render(await SecurityPage());
    expect(screen.getByLabelText(/current password/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^new password$/i)).toBeInTheDocument();
    // Deletion must not present a ready-to-submit form on first paint.
    expect(screen.queryByLabelText(/type DELETE/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /delete.*account/i })).toBeInTheDocument();
  });
});
