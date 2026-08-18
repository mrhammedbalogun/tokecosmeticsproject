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
    shipping_total: "2000.00", tax_total: "0.00", tax_label: "VAT", grand_total: "42000.00",
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

const render_ = async (
  number = "TC-100038",
  search: Record<string, string> = {},
) =>
  render(
    await OrderDetailPage({
      params: Promise.resolve({ number }),
      searchParams: Promise.resolve(search),
    }),
  );

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

  // The canonical per-status list now lives in TrackingBlock's own tests, which own the
  // PRE_SHIP ruling. What these cases prove is narrower and still worth keeping: that THIS
  // page wires the block up and renders it in the right place.
  it.each([["pending_payment"], ["processing"]])(
    "shows the pre-ship hint for a %s order",
    async (status) => {
      respond(order({ status }));
      await render_();

      expect(screen.getByRole("heading", { name: "Tracking" })).toBeInTheDocument();
      expect(screen.getByText(/tracking details when your order ships/i)).toBeInTheDocument();
    },
  );

  it.each([["cancelled"], ["expired"], ["refunded"], ["delivered"], ["completed"], ["shipped"]])(
    "omits the whole tracking section on a %s order with no tracking recorded",
    async (status) => {
      // The hint promises a shipment. Nothing is reserved or paid on cancelled/expired/
      // refunded, delivered/completed are already there, and shipped-without-tracking has
      // nothing to add — silence beats an empty section or a false promise.
      respond(order({ status }));
      await render_();

      expect(screen.queryByRole("heading", { name: "Tracking" })).not.toBeInTheDocument();
      expect(screen.queryByText(/tracking details when your order ships/i)).not.toBeInTheDocument();
    },
  );

  it("omits the tracking hint on an on_hold order", async () => {
    // on_hold is the triage state for migrated legacy orders and for the Plan-14a
    // freight-declined cohort — customers who are owed a REFUND. "Tracking is coming" is
    // a false promise about the wrong direction of money.
    respond(order({ status: "on_hold" }));
    await render_();

    expect(screen.queryByText(/tracking details when your order ships/i)).not.toBeInTheDocument();
  });

  it("still shows real tracking on an on_hold order that has some", async () => {
    // Omitting the hint must not omit facts: an order held after shipping still has a
    // consignment the customer can chase.
    respond(order({ status: "on_hold", tracking_carrier: "GIG", tracking_number: "GX9911" }));
    await render_();

    expect(screen.getByText("GIG · GX9911")).toBeInTheDocument();
  });

  it("renders bank details for an unpaid bank transfer", async () => {
    respond(order({ payment_gateway: "bank_transfer", status: "pending_payment" }));
    await render_();

    expect(screen.getByRole("heading", { name: /payment details/i })).toBeInTheDocument();
  });

  it.each([["delivered"], ["cancelled"], ["refunded"]])(
    "does not render bank details for a %s bank-transfer order",
    async (status) => {
      // confirmationCopy's bank_transfer branch ignores status — correct on the
      // confirmation page, a duplicate-payment trap in order history years later.
      respond(order({ payment_gateway: "bank_transfer", status }));
      await render_();

      expect(screen.queryByRole("heading", { name: /payment details/i })).not.toBeInTheDocument();
    },
  );

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

  it("links the invoice at the BFF route WITHOUT a download attribute", async () => {
    await render_();

    const link = screen.getByRole("link", { name: /download invoice/i });
    expect(link).toHaveAttribute("href", "/api/orders/TC-100038/invoice");
    // Absent on purpose — the ruling is on the <a> in page.tsx. Do not re-add it.
    expect(link).not.toHaveAttribute("download");
  });

  it("explains an invoice failure when the BFF route bounces back with the flag", async () => {
    await render_("TC-100038", { invoice: "unavailable" });

    expect(screen.getByRole("status")).toHaveTextContent(
      /couldn't generate your invoice just now/i,
    );
  });

  it("shows no invoice notice without the flag", async () => {
    await render_();

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText(/couldn't generate your invoice/i)).not.toBeInTheDocument();
  });

  it("ignores an invoice param with any other value", async () => {
    await render_("TC-100038", { invoice: "yes" });

    expect(screen.queryByText(/couldn't generate your invoice/i)).not.toBeInTheDocument();
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
