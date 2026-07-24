import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { CheckoutProvider, useCheckout } from "@/components/checkout/CheckoutContext";
import { AddressStep } from "@/components/checkout/AddressStep";
import type { Cart } from "@/lib/cart-types";

/** AddressStep reads the shopping country from useCart().cart.country — mock it the
 * same way CartView.test.tsx does so each test can pin the country independently. */
let mockCart: Cart;
vi.mock("@/hooks/useCart", () => ({
  useCart: () => ({
    cart: mockCart,
    isLoading: false,
    addItem: { mutate: vi.fn() },
    setQty: { mutate: vi.fn() },
  }),
}));

function makeCart(overrides: Partial<Cart> = {}): Cart {
  return {
    id: "cart-1",
    kind: "standard",
    status: "active",
    country: "GB",
    currency: "GBP",
    items: [],
    subtotal: "0.00",
    has_unavailable: false,
    ...overrides,
  };
}

/** Small harness exposing the checkout machine's completed/selections state next to
 * the real AddressStep, mirroring SignInStep.test.tsx's Harness pattern. */
function Harness() {
  const { completed, selections } = useCheckout();
  return (
    <div>
      <p data-testid="completed">{[...completed].sort().join(",")}</p>
      <p data-testid="addressId">{String(selections.addressId ?? "")}</p>
      <p data-testid="addressDisplay">{selections.addressDisplay ?? ""}</p>
      <AddressStep />
    </div>
  );
}

function renderHarness() {
  return render(
    <CheckoutProvider>
      <Harness />
    </CheckoutProvider>
  );
}

type Route = { status: number; body: unknown };

/** Routes fetch calls by "METHOD url" (GET and POST both hit /api/addresses, so a
 * URL-only map like SignInStep.test.tsx's isn't enough here). */
function mockFetch(routes: Record<string, Route>) {
  const f = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url}`;
    const route = routes[key];
    if (!route) return Promise.reject(new Error(`unexpected fetch: ${key}`));
    return Promise.resolve(
      new Response(JSON.stringify(route.body), {
        status: route.status,
        headers: { "content-type": "application/json" },
      })
    );
  });
  global.fetch = f as unknown as typeof fetch;
  return f;
}

const originalFetch = global.fetch;

beforeEach(() => {
  mockCart = makeCart();
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("AddressStep", () => {
  it("renders saved addresses as cards and selecting one sets addressId and completes step 2", async () => {
    mockFetch({
      "GET /api/addresses": {
        status: 200,
        body: [
          {
            id: 1, label: "Home", first_name: "Ada", phone: "0700",
            line1: "1 Baker St", country_code: "GB", city_text: "London", postcode: "NW1",
            is_default_shipping: true, is_default_billing: true,
          },
          {
            id: 2, label: "Office", first_name: "Ada", phone: "0700",
            line1: "2 Fleet St", country_code: "GB", city_text: "London", postcode: "EC4",
            is_default_shipping: false, is_default_billing: false,
          },
        ],
      },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByText("2 Fleet St, London")).toBeInTheDocument());

    // The default (id 1) is preselected — visually checked — but nothing has
    // completed yet; only an explicit click advances the step.
    const homeCard = screen.getByText("1 Baker St, London").closest("[role='radio']")!;
    expect(homeCard).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("completed")).toHaveTextContent("");

    const officeCard = screen.getByText("2 Fleet St, London").closest("[role='radio']")!;
    fireEvent.click(officeCard);

    await waitFor(() => expect(screen.getByTestId("completed")).toHaveTextContent("2"));
    expect(screen.getByTestId("addressId")).toHaveTextContent("2");
    expect(screen.getByTestId("addressDisplay")).toHaveTextContent("2 Fleet St, London");
  });

  it("adds a new address (happy path): fills required fields, POSTs, selects it, and completes step 2", async () => {
    mockFetch({
      "GET /api/addresses": { status: 200, body: [] },
      "POST /api/addresses": {
        status: 201,
        body: {
          id: 9, first_name: "Ada", phone: "07000000000", line1: "10 Downing St",
          country_code: "GB", city_text: "London", postcode: "SW1A 2AA",
          is_default_shipping: false, is_default_billing: false,
        },
      },
    });

    renderHarness();

    // No saved addresses -> the add-new form opens directly.
    await waitFor(() => expect(screen.getByLabelText(/street address/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText(/^phone$/i), { target: { value: "07000000000" } });
    fireEvent.change(screen.getByLabelText(/street address/i), { target: { value: "10 Downing St" } });
    fireEvent.change(screen.getByLabelText(/^city\/town$/i), { target: { value: "London" } });
    fireEvent.change(screen.getByLabelText(/^postcode$/i), { target: { value: "SW1A 2AA" } });

    fireEvent.click(screen.getByRole("button", { name: /save address/i }));

    await waitFor(() => expect(screen.getByTestId("completed")).toHaveTextContent("2"));
    expect(screen.getByTestId("addressId")).toHaveTextContent("9");
    expect(screen.getByTestId("addressDisplay")).toHaveTextContent("10 Downing St, London");
  });

  it("shows a field error on a 400 create response and does not complete the step", async () => {
    mockFetch({
      "GET /api/addresses": { status: 200, body: [] },
      "POST /api/addresses": {
        status: 400,
        body: { postcode: ["This field is required for this country."] },
      },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByLabelText(/street address/i)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText(/^phone$/i), { target: { value: "07000000000" } });
    fireEvent.change(screen.getByLabelText(/street address/i), { target: { value: "10 Downing St" } });
    fireEvent.change(screen.getByLabelText(/^city\/town$/i), { target: { value: "London" } });

    fireEvent.click(screen.getByRole("button", { name: /save address/i }));

    await waitFor(() =>
      expect(screen.getByText(/required for this country/i)).toBeInTheDocument()
    );
    expect(screen.getByText(/required for this country/i)).toHaveAttribute("role", "alert");
    expect(screen.getByTestId("completed")).toHaveTextContent("");
    expect(screen.getByTestId("addressId")).toHaveTextContent("");
  });

  it("opens the NG add-new form with a State/LGA RegionSelect instead of text fields", async () => {
    mockCart = makeCart({ country: "NG" });
    mockFetch({
      "GET /api/addresses": { status: 200, body: [] },
      "GET /api/regions?country=NG": {
        status: 200,
        body: [{ id: 1, name: "Lagos", level: "state", has_children: true }],
      },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByLabelText(/^state$/i)).toBeInTheDocument());
    expect(screen.queryByLabelText(/^city\/town$/i)).toBeNull();
    await waitFor(() => expect(screen.getByRole("option", { name: "Lagos" })).toBeInTheDocument());
  });
});
