import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { OrderListItem, Paginated } from "@/lib/orders";

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

import OrdersPage from "../page";

function order(overrides: Partial<OrderListItem> = {}): OrderListItem {
  return {
    number: "TC-100038", status: "pending_payment", placed_at: "2026-07-24T10:30:00Z",
    currency: "NGN", grand_total: "42000.00", grand_total_display: "₦42,000.00",
    item_count: 3, items: [], ...overrides,
  };
}

function page(overrides: Partial<Paginated<OrderListItem>> = {}): Paginated<OrderListItem> {
  return { count: 1, next: null, previous: null, results: [order()], ...overrides };
}

/** Every request the page makes resolves to this payload; `lastUrl` lets a test assert
 * which upstream page was actually requested. */
let lastUrl = "";
function respond(body: unknown, status = 200) {
  global.fetch = vi.fn(async (url: string | URL | Request) => {
    lastUrl = String(url);
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
  respond(page());
});
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

const render_ = async (params: Record<string, string | string[]> = {}) =>
  render(await OrdersPage({ searchParams: Promise.resolve(params) }));

describe("orders list page", () => {
  it("renders a row per order with number, date, status, count and total", async () => {
    await render_();

    expect(screen.getByRole("link", { name: /TC-100038/ })).toHaveAttribute(
      "href", "/account/orders/TC-100038",
    );
    expect(screen.getByText(/24 Jul 2026/)).toBeInTheDocument();
    expect(screen.getByText(/3 items/)).toBeInTheDocument();
    expect(screen.getByText("Awaiting payment")).toBeInTheDocument();
    expect(screen.getByText("₦42,000.00")).toBeInTheDocument();
  });

  it("singularises a one-item order", async () => {
    respond(page({ results: [order({ item_count: 1 })] }));
    await render_();

    expect(screen.getByText(/1 item(?!s)/)).toBeInTheDocument();
  });

  it("shows the empty state with a link to the catalog when there are no orders", async () => {
    respond(page({ count: 0, results: [] }));
    await render_();

    expect(screen.getByText(/haven’t placed an order/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /browse products/i })).toHaveAttribute(
      "href", "/products",
    );
    expect(screen.queryByRole("navigation", { name: /pagination/i })).not.toBeInTheDocument();
  });

  it("hides Prev on the first page and shows Next when the API says there is more", async () => {
    respond(page({ count: 30, next: "http://backend:8000/api/v1/orders/?page=2" }));
    await render_();

    expect(screen.queryByRole("link", { name: /prev/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /next/i })).toHaveAttribute(
      "href", "/account/orders?page=2",
    );
  });

  it("hides Next on the last page and shows Prev", async () => {
    respond(page({ count: 30, previous: "http://backend:8000/api/v1/orders/?page=1" }));
    await render_({ page: "2" });

    expect(screen.getByRole("link", { name: /prev/i })).toHaveAttribute(
      "href", "/account/orders?page=1",
    );
    expect(screen.queryByRole("link", { name: /next/i })).not.toBeInTheDocument();
    expect(screen.getByText("Page 2")).toBeInTheDocument();
  });

  it.each([["abc"], ["0"], ["-3"], ["1.5"], [""]])(
    "falls back to page 1 for junk page param %j",
    async (raw) => {
      await render_({ page: raw });

      // Junk is never forwarded verbatim to DRF.
      expect(lastUrl).toBe("http://backend:8000/api/v1/orders/?page=1");
    },
  );

  it("collapses a repeated page param to its first value", async () => {
    // `?page=2&page=9` arrives as string[]; without first() the array stringifies into
    // the query ("2,9") and DRF 400s.
    respond(page({ count: 30, previous: "http://backend:8000/api/v1/orders/?page=1" }));
    await render_({ page: ["2", "9"] });

    expect(lastUrl).toBe("http://backend:8000/api/v1/orders/?page=2");
  });

  it("404s (out-of-range page) become notFound(), not a 500", async () => {
    respond({ detail: "Invalid page." }, 404);

    await expect(render_({ page: "99" })).rejects.toBeInstanceOf(NotFound);
  });

  it("lets a renewal bounce through, aimed back at the same page", async () => {
    respond({ detail: "token not valid" }, 401);

    await expect(render_({ page: "3" })).rejects.toMatchObject({
      to: expect.stringContaining(encodeURIComponent("/account/orders?page=3")),
    });
  });
});
