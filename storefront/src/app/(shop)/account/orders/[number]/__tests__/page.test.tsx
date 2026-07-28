import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { OrderDetail } from "@/lib/orders";

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

import OrderDetailPage, { generateMetadata } from "../page";

function order(overrides: Partial<OrderDetail> = {}): OrderDetail {
  return {
    number: "TC-100038", status: "pending_payment", placed_at: "2026-07-24T23:30:00Z",
    currency: "NGN", subtotal: "40000.00", discount_total: "0.00",
    shipping_total: "2000.00", tax_total: "0.00", grand_total: "42000.00",
    grand_total_display: "₦42,000.00", delivery_option_name: "Lagos same-day",
    shipping_address: { first_name: "Ada", last_name: "Obi", line1: "12 Marina", city_text: "Lagos" },
    billing_address: null, customer_note: "Please call on arrival.",
    payment_gateway: "bank_transfer", tracking_carrier: "", tracking_number: "",
    items: [{
      product_name: "Shea Butter", variant_name: "Size: 150ml", sku: "SB-150",
      quantity: 2, unit_price: "20000.00", line_total: "40000.00",
      unit_price_display: "₦20,000.00", line_total_display: "₦40,000.00", image_url: null,
    }],
    ...overrides,
  };
}

let lastUrl = "";
let lastInit: RequestInit | undefined;
function respond(body: unknown, status = 200) {
  global.fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    lastUrl = String(url);
    lastInit = init;
    return new Response(JSON.stringify(body), {
      status, headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof fetch;
}

const originalFetch = global.fetch;
beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  store.clear();
  store.set("access", "AAA");
  store.set("refresh", "RRR");
  lastUrl = "";
  lastInit = undefined;
  respond(order());
});
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

const render_ = async (number = "TC-100038") =>
  render(await OrderDetailPage({ params: Promise.resolve({ number }) }));

describe("account order detail page", () => {
  it("renders heading, date, status, items, totals, address, method and note", async () => {
    await render_();

    expect(screen.getByRole("heading", { name: "Order TC-100038" })).toBeInTheDocument();
    expect(screen.getByText(/24 Jul 2026/)).toBeInTheDocument();
    expect(screen.getByText("Awaiting payment")).toBeInTheDocument();
    expect(screen.getByText("Shea Butter")).toBeInTheDocument();
    expect(screen.getByText("₦42,000.00")).toBeInTheDocument();
    expect(screen.getByText("12 Marina")).toBeInTheDocument();
    expect(screen.getByText("Lagos same-day")).toBeInTheDocument();
    expect(screen.getByText("Please call on arrival.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to orders/i })).toHaveAttribute(
      "href", "/account/orders",
    );
  });

  it("titles the tab with the order number", async () => {
    expect(await generateMetadata({ params: Promise.resolve({ number: "TC-100038" }) }))
      .toEqual({ title: "Order TC-100038" });
  });

  it("shows carrier and number when both are set", async () => {
    respond(order({ status: "shipped", tracking_carrier: "GIG", tracking_number: "GX9911" }));
    await render_();

    expect(screen.getByRole("heading", { name: "Tracking" })).toBeInTheDocument();
    expect(screen.getByText("GIG · GX9911")).toBeInTheDocument();
  });

  it("shows whichever tracking field is set on its own, with no stray separator", async () => {
    respond(order({ status: "shipped", tracking_carrier: "", tracking_number: "GX9911" }));
    await render_();

    expect(screen.getByText("GX9911")).toBeInTheDocument();
  });

  it("shows the pre-ship hint for an order that has not shipped yet", async () => {
    respond(order({ status: "processing" }));
    await render_();

    expect(screen.getByRole("heading", { name: "Tracking" })).toBeInTheDocument();
    expect(screen.getByText(/tracking details when your order ships/i)).toBeInTheDocument();
  });

  it("omits the whole tracking section on a cancelled order", async () => {
    // The hint would be a lie and the section would be empty — silence is the answer.
    respond(order({ status: "cancelled" }));
    await render_();

    expect(screen.queryByRole("heading", { name: "Tracking" })).not.toBeInTheDocument();
    expect(screen.queryByText(/tracking details when your order ships/i)).not.toBeInTheDocument();
  });

  it("omits the tracking section on a shipped order with no tracking recorded", async () => {
    respond(order({ status: "shipped" }));
    await render_();

    expect(screen.queryByRole("heading", { name: "Tracking" })).not.toBeInTheDocument();
  });

  it("renders bank details for an unpaid bank transfer", async () => {
    respond(order({ payment_gateway: "bank_transfer", status: "pending_payment" }));
    await render_();

    expect(screen.getByRole("heading", { name: /payment details/i })).toBeInTheDocument();
  });

  it("does not render bank details for a paid card order", async () => {
    respond(order({ payment_gateway: "paystack", status: "processing" }));
    await render_();

    expect(screen.queryByRole("heading", { name: /payment details/i })).not.toBeInTheDocument();
  });

  it("never repeats the confirmation banner copy", async () => {
    // The predicate is shared with the confirmation page; the just-placed-an-order
    // language is not — it reads as nonsense weeks later in order history.
    await render_();

    expect(screen.queryByText(/your order is reserved/i)).not.toBeInTheDocument();
  });

  it("links the invoice at the BFF route", async () => {
    await render_();

    expect(screen.getByRole("link", { name: /download invoice/i })).toHaveAttribute(
      "href", "/api/orders/TC-100038/invoice",
    );
  });

  it("URL-encodes the order number in the invoice href", async () => {
    // `params` arrives decoded; an unencoded "#" truncates the path at the fragment and
    // "/" invents a route segment, so the BFF route would never see the real number.
    respond(order({ number: "TC#1/2" }));
    await render_("TC#1/2");

    expect(screen.getByRole("link", { name: /download invoice/i })).toHaveAttribute(
      "href", "/api/orders/TC%231%2F2/invoice",
    );
  });

  it("fetches the detail endpoint and forwards the country cookie", async () => {
    store.set("country", "GB");
    await render_();

    expect(lastUrl).toBe("http://backend:8000/api/v1/orders/TC-100038/");
    expect(new Headers(lastInit?.headers).get("X-Country")).toBe("GB");
  });

  it("404s become notFound()", async () => {
    respond({ detail: "Not found." }, 404);

    await expect(render_()).rejects.toBeInstanceOf(NotFound);
  });

  it("403s become notFound() too, so a stranger's order cannot be probed", async () => {
    // The backend owner-filters, so a 403 here would confirm the order exists.
    respond({ detail: "Forbidden." }, 403);

    await expect(render_()).rejects.toBeInstanceOf(NotFound);
  });

  it("lets a renewal bounce through, aimed back at this page's encoded path", async () => {
    respond({ detail: "token not valid" }, 401);

    await expect(render_("TC#1/2")).rejects.toMatchObject({
      to: expect.stringContaining(encodeURIComponent("/account/orders/TC%231%2F2")),
    });
  });
});
