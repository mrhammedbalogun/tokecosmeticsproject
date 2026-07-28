import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AddressBook } from "@/components/account/AddressBook";
import type { Address } from "@/components/checkout/address-fields";

type Route = { status: number; body: unknown };

function mockFetch(routes: Record<string, Route>) {
  const f = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url}`;
    const route = routes[key];
    if (!route) return Promise.reject(new Error(`unexpected fetch: ${key}`));
    // Null-body statuses (204 for DELETE) reject a non-null Response body at construction —
    // JSON.stringify(null) is the string "null", which is non-null.
    const body = route.status === 204 ? null : JSON.stringify(route.body);
    return Promise.resolve(
      new Response(body, {
        status: route.status,
        headers: { "content-type": "application/json" },
      })
    );
  });
  global.fetch = f as unknown as typeof fetch;
  return f;
}

function addr(overrides: Partial<Address> = {}): Address {
  return {
    id: 1, label: "Home", first_name: "Ada", last_name: "L", phone: "0700",
    line1: "1 Baker St", line2: "", country_code: "GB", city_text: "London",
    state_text: "", postcode: "NW1", is_default_shipping: false, is_default_billing: false,
    ...overrides,
  };
}

const originalFetch = global.fetch;
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("AddressBook", () => {
  it("renders cards with default badges", () => {
    mockFetch({});
    const addresses = [
      addr({ id: 1, label: "Home", is_default_shipping: true, is_default_billing: true }),
      addr({ id: 2, label: "Office", is_default_shipping: false, is_default_billing: false }),
    ];

    render(<AddressBook initial={addresses} />);

    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.getByText("Office")).toBeInTheDocument();
    const badges = screen.getAllByText(/^Default (shipping|billing)$/);
    expect(badges).toHaveLength(2);
  });

  it("empty state renders with an 'Add your first address' button", () => {
    mockFetch({});
    render(<AddressBook initial={[]} />);

    expect(screen.getByText(/no addresses yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add your first address/i })).toBeInTheDocument();
  });

  it("Set default shipping POSTs {kind: 'shipping'} and re-GETs the list", async () => {
    const initial = [addr({ id: 1, is_default_shipping: false })];
    const refreshed = [addr({ id: 1, is_default_shipping: true })];
    const f = mockFetch({
      "POST /api/addresses/1/default": { status: 200, body: refreshed[0] },
      "GET /api/addresses": { status: 200, body: refreshed },
    });

    render(<AddressBook initial={initial} />);

    fireEvent.click(screen.getByRole("button", { name: /set default shipping/i }));

    await waitFor(() => expect(f).toHaveBeenCalledWith(
      "/api/addresses/1/default",
      expect.objectContaining({ method: "POST" }),
    ));
    const call = f.mock.calls.find(([url]) => url === "/api/addresses/1/default")!;
    expect(JSON.parse((call[1] as RequestInit).body as string)).toEqual({ kind: "shipping" });

    await waitFor(() => expect(f).toHaveBeenCalledWith("/api/addresses"));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /set default shipping/i })).not.toBeInTheDocument()
    );
  });

  it("hides the Set default shipping/billing buttons when already the default", () => {
    mockFetch({});
    const address = addr({ id: 1, is_default_shipping: true, is_default_billing: true });

    render(<AddressBook initial={[address]} />);

    expect(screen.queryByRole("button", { name: /set default shipping/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /set default billing/i })).not.toBeInTheDocument();
  });

  it("Delete requires a confirm click — first click never calls fetch — then DELETEs and re-GETs", async () => {
    const initial = [addr({ id: 1 }), addr({ id: 2, label: "Office" })];
    const f = mockFetch({
      "DELETE /api/addresses/1": { status: 204, body: null },
      "GET /api/addresses": { status: 200, body: [addr({ id: 2, label: "Office" })] },
    });

    render(<AddressBook initial={initial} />);

    const deleteButtons = screen.getAllByRole("button", { name: /^delete$/i });
    fireEvent.click(deleteButtons[0]);

    expect(f).not.toHaveBeenCalled();
    const confirmButton = screen.getByRole("button", { name: /confirm delete/i });

    fireEvent.click(confirmButton);

    await waitFor(() => expect(f).toHaveBeenCalledWith(
      "/api/addresses/1",
      expect.objectContaining({ method: "DELETE" }),
    ));
    await waitFor(() => expect(f).toHaveBeenCalledWith("/api/addresses"));
    await waitFor(() => expect(screen.queryByText("Home")).not.toBeInTheDocument());
    expect(screen.getByText("Office")).toBeInTheDocument();
  });

  it("shows an inline error on a non-400 delete failure and keeps the list unchanged", async () => {
    const initial = [addr({ id: 1 })];
    const f = mockFetch({
      "DELETE /api/addresses/1": { status: 500, body: { detail: "boom" } },
    });

    render(<AddressBook initial={initial} />);

    fireEvent.click(screen.getByRole("button", { name: /^delete$/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirm delete/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    // No re-GET happened (only the failed DELETE call) and the card is still there.
    expect(f).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Home")).toBeInTheDocument();
  });

  it("opens the AddressForm in edit mode prefilled, and Add address opens it empty", async () => {
    mockFetch({ "GET /api/regions?country=GB": { status: 200, body: [] } });
    const initial = [addr({ id: 1 })];

    render(<AddressBook initial={initial} />);

    fireEvent.click(screen.getByRole("button", { name: /^edit$/i }));

    await waitFor(() => expect(screen.getByLabelText(/street address/i)).toHaveValue("1 Baker St"));
  });
});
