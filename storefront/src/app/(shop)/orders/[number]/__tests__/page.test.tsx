import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { OrderTracking } from "@/lib/orders";

// The page reads no cookies and takes no auth path, but `lib/orders` imports `lib/session`
// (and `next/navigation`) for its authed siblings, so both still have to be stubbed for
// the module to load. A cookie jar with a live session is set up deliberately: this page
// must behave identically whether or not the visitor happens to be signed in.
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
class NotFound extends Error {
  constructor() { super("NEXT_NOT_FOUND"); }
}
vi.mock("next/navigation", () => ({
  redirect: (to: string) => { throw new Redirected(to); },
  notFound: () => { throw new NotFound(); },
}));

import OrderTrackingPage, { metadata } from "../page";

/** The REDACTED payload — exactly the fields `OrderTrackingSerializer` lists, nothing
 * more. Tests that need to prove a field is not rendered add it as an override. */
function tracked(overrides: Partial<OrderTracking> = {}): OrderTracking {
  return {
    number: "TC-100038", status: "pending_payment", placed_at: "2026-07-24T23:30:00Z",
    currency: "NGN", grand_total: "42000.00", grand_total_display: "₦42,000.00",
    delivery_option_name: "Lagos same-day", tracking_carrier: "", tracking_number: "",
    items: [{
      product_name: "Shea Butter", variant_name: "Size: 150ml", sku: "SB-150",
      quantity: 2, unit_price: "20000.00", line_total: "40000.00",
      unit_price_display: "₦20,000.00", line_total_display: "₦40,000.00", image_url: null,
    }],
    ...overrides,
  };
}

let fetchMock: ReturnType<typeof vi.fn>;
let lastUrl = "";
let lastInit: RequestInit | undefined;
function respond(body: unknown, status = 200) {
  fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    lastUrl = String(url);
    lastInit = init;
    return new Response(JSON.stringify(body), {
      status, headers: { "content-type": "application/json" },
    });
  });
  global.fetch = fetchMock as unknown as typeof fetch;
}

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.clear();
  store.set("access", "AAA");
  store.set("refresh", "RRR");
  lastUrl = "";
  lastInit = undefined;
  respond(tracked());
});
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

const render_ = async (
  number = "TC-100038",
  search: Record<string, string | string[]> = { token: "GOOD" },
) =>
  render(
    await OrderTrackingPage({
      params: Promise.resolve({ number }),
      searchParams: Promise.resolve(search),
    }),
  );

const invalidHeading = /tracking link is invalid or has expired/i;

describe("guest order tracking page", () => {
  it("renders heading, date, status, delivery method, items and total", async () => {
    await render_();

    expect(screen.getByRole("heading", { name: "Order TC-100038" })).toBeInTheDocument();
    expect(screen.getByText(/24 Jul 2026/)).toBeInTheDocument();
    expect(screen.getByText("Awaiting payment")).toBeInTheDocument();
    expect(screen.getByText("Lagos same-day")).toBeInTheDocument();
    expect(screen.getByText("Shea Butter")).toBeInTheDocument();
    expect(screen.getByText("Total")).toBeInTheDocument();
    expect(screen.getByText("₦42,000.00")).toBeInTheDocument();
  });

  it("omits the delivery method section when the order has none", async () => {
    respond(tracked({ delivery_option_name: null }));
    await render_();

    expect(screen.queryByRole("heading", { name: "Delivery method" })).not.toBeInTheDocument();
  });

  it("shows the invalid-link state and calls NOTHING upstream when there is no token", async () => {
    // The backend 403s an anonymous caller without a token, so there is nothing to ask it.
    await render_("TC-100038", {});

    expect(screen.getByRole("heading", { name: invalidHeading })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the invalid-link state for a bad, expired or mismatched token", async () => {
    respond({ error: "invalid_token" }, 404);
    await render_();

    expect(screen.getByRole("heading", { name: invalidHeading })).toBeInTheDocument();
  });

  it("reveals nothing about the order in the invalid-link state", async () => {
    // The backend's invalid_token 404 is deliberately indistinguishable from an order
    // that never existed. This page must not undo that by leaking status or totals.
    respond({ error: "invalid_token" }, 404);
    await render_();

    expect(screen.queryByRole("heading", { name: /^Order / })).not.toBeInTheDocument();
    expect(screen.queryByText("Awaiting payment")).not.toBeInTheDocument();
    expect(screen.queryByText("₦42,000.00")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Items" })).not.toBeInTheDocument();
  });

  it("offers a sign-in link and a shopping link on the invalid-link state", async () => {
    await render_("TC-100038", {});

    expect(screen.getByRole("link", { name: /sign in to view your order/i })).toHaveAttribute(
      "href", "/account/orders/TC-100038",
    );
    expect(screen.getByRole("link", { name: /continue shopping/i })).toHaveAttribute(
      "href", "/products",
    );
  });

  it("URL-encodes the order number in the sign-in link", async () => {
    // `params` arrives DECODED; an unencoded "/" would invent a route segment and land the
    // customer on a page that does not exist.
    await render_("TC#1/2", {});

    expect(screen.getByRole("link", { name: /sign in to view your order/i })).toHaveAttribute(
      "href", "/account/orders/TC%231%2F2",
    );
  });

  it("rethrows a server error instead of pretending the link expired", async () => {
    // A 5xx must surface as an error page. Swallowing it would tell a customer holding a
    // perfectly good link that it had expired, over what is really our outage.
    respond({ detail: "boom" }, 500);

    await expect(render_()).rejects.toMatchObject({ status: 500 });
  });

  it("encodes both the order number and the token into the upstream URL", async () => {
    // A signed token is base64-ish and can carry "+" and "/"; unencoded, "+" decodes back
    // as a space server-side and the backend reads a mangled token as invalid.
    await render_("TC#1/2", { token: "a+b/c" });

    expect(lastUrl).toBe("http://backend:8000/api/v1/orders/TC%231%2F2/?token=a%2Bb%2Fc");
  });

  it("never sends the visitor's session upstream", async () => {
    // Public page: the token IS the credential. An Authorization header here would mean an
    // auth fetcher had crept in, which is the thing that bounces guests to login.
    await render_();

    expect(new Headers(lastInit?.headers).get("Authorization")).toBeNull();
    expect(lastInit?.cache).toBe("no-store");
  });

  it("takes the first value of a repeated token param", async () => {
    await render_("TC-100038", { token: ["GOOD", "OTHER"] });

    expect(lastUrl).toContain("token=GOOD");
  });

  it("shows carrier and number when both are set", async () => {
    respond(tracked({ status: "shipped", tracking_carrier: "GIG", tracking_number: "GX9911" }));
    await render_();

    expect(screen.getByRole("heading", { name: "Tracking" })).toBeInTheDocument();
    expect(screen.getByText("GIG · GX9911")).toBeInTheDocument();
  });

  it("shows whichever tracking field is set on its own, with no stray separator", async () => {
    respond(tracked({ status: "shipped", tracking_carrier: "", tracking_number: "GX9911" }));
    await render_();

    expect(screen.getByText("GX9911")).toBeInTheDocument();
  });

  it("shows the pre-ship hint for a pending_payment order with no tracking", async () => {
    await render_();

    expect(screen.getByRole("heading", { name: "Tracking" })).toBeInTheDocument();
    expect(screen.getByText(/tracking details when your order ships/i)).toBeInTheDocument();
  });

  it("omits the whole tracking section on a cancelled order", async () => {
    // Same PRE_SHIP ruling as the account detail page — nothing is owed, so promise none.
    respond(tracked({ status: "cancelled" }));
    await render_();

    expect(screen.queryByRole("heading", { name: "Tracking" })).not.toBeInTheDocument();
    expect(screen.queryByText(/tracking details when your order ships/i)).not.toBeInTheDocument();
  });

  it("renders no address, no invoice link and no totals breakdown, even if the API sends them", async () => {
    // The redacted serializer carries none of these today. Overriding them in proves the
    // page is the second line of defence: a backend regression that widened
    // OrderTrackingSerializer must not turn a forwardable email link into an address leak.
    respond({
      ...tracked(),
      shipping_address: { first_name: "Ada", last_name: "Obi", line1: "12 Marina", city_text: "Lagos" },
      subtotal: "40000.00", shipping_total: "2000.00", tax_total: "0.00", discount_total: "0.00",
      customer_note: "Please call on arrival.", payment_gateway: "bank_transfer",
    });
    await render_();

    expect(screen.queryByText("12 Marina")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /delivery address/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Subtotal")).not.toBeInTheDocument();
    expect(screen.queryByText("Tax")).not.toBeInTheDocument();
    expect(screen.queryByText("Please call on arrival.")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /invoice/i })).not.toBeInTheDocument();
    expect(document.querySelector('a[href*="/invoice"]')).toBeNull();
  });

  it("keeps the order number out of the tab title and stays out of the index", async () => {
    // The title lands in browser history and syncs across shared devices; the heading
    // already names the order to whoever is actually looking at the page.
    expect(metadata.title).toBe("Track order");
    expect(String(metadata.title)).not.toMatch(/TC-/);
    expect(metadata.robots).toEqual({ index: false, follow: false });
  });
});
