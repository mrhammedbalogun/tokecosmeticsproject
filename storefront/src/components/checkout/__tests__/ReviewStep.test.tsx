import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useEffect } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CheckoutProvider, useCheckout } from "@/components/checkout/CheckoutContext";
import { ReviewStep } from "@/components/checkout/ReviewStep";
import { readBankHandoff } from "@/lib/bank-handoff";
import type { Cart } from "@/lib/cart-types";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

/** ReviewStep reads cart.id/items/currency/subtotal from useCart() — mock it the
 * same way DeliveryStep.test.tsx does so each test can pin the cart independently. */
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
    items: [
      { id: 1, variant_id: 1, sku: "SKU1", name: "Rose Serum", variant_name: {}, quantity: 2, unit_price: "10.00", line_total: "20.00", unavailable: false },
    ],
    subtotal: "20.00",
    has_unavailable: false,
    ...overrides,
  };
}

/** Harness: seeds selections the way steps 1-4 would have left them (via
 * setSelection, which shallow-merges without touching the step machine — same
 * escape hatch CheckoutContext exposes for exactly this kind of test seeding),
 * then renders the real ReviewStep next to the machine's state for assertions. */
function Harness() {
  const { selections, setSelection } = useCheckout();
  useEffect(() => {
    setSelection({
      addressId: 7,
      addressDisplay: "1 Rose St, London",
      deliveryOptionId: 2,
      deliveryDisplay: "Standard — £5.00",
      paymentGateway: "bank_transfer",
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div>
      <p data-testid="note">{selections.note}</p>
      <ReviewStep />
    </div>
  );
}

function renderHarness() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <CheckoutProvider>
        <Harness />
      </CheckoutProvider>
    </QueryClientProvider>
  );
}

type Route = { status: number; body: unknown };

/** Routes fetch calls by exact URL; `routes` maps a URL to a canned Response. Second
 * param is typed (even though unused in the body) so `mock.calls[i][1]` — used below
 * to assert the POST body — type-checks as a 2-tuple. */
function mockFetch(routes: Record<string, Route>) {
  const f = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const route = routes[url];
    if (!route) return Promise.reject(new Error(`unexpected fetch: ${url}`));
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

const QUOTE_URL = "/api/checkout/quote";
const PLACE_URL = "/api/checkout";

const originalFetch = global.fetch;

beforeEach(() => {
  mockCart = makeCart();
  sessionStorage.clear();
  push.mockClear();
});
afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("ReviewStep", () => {
  it("quotes on mount and shows the authoritative grand total", async () => {
    mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "0.00", delivery: "5.00", tax: "0.00", grand_total: "25.00", currency: "GBP" }, coupon: { ok: true } },
      },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByText("£25.00")).toBeInTheDocument());
  });

  it("places the order with expected_total from the quote and the stashed coupon code, then navigates + stashes bank details", async () => {
    sessionStorage.setItem("toke-coupon-code", "SAVE10");
    const f = mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "2.00", delivery: "5.00", tax: "0.00", grand_total: "23.00", currency: "GBP" }, coupon: { ok: true } },
      },
      [PLACE_URL]: {
        status: 201,
        body: {
          order_number: "TC-100",
          payment: { gateway: "bank_transfer", action: "bank_details", data: { display: { Bank: "GTB", "Account number": "0011" }, reference: "TC-100", instructions: "Use your order number." } },
        },
      },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByText("£23.00")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /place order/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/checkout/confirmation/TC-100"));

    const placeCall = f.mock.calls.find((c) => c[0] === PLACE_URL)!;
    const body = JSON.parse((placeCall[1] as RequestInit).body as string);
    expect(body).toMatchObject({
      cart_id: "cart-1",
      address_id: 7,
      delivery_option_id: 2,
      payment_gateway: "bank_transfer",
      coupon_code: "SAVE10",
      expected_total: "23.00",
    });
    expect(typeof body.idempotency_key).toBe("string");
    expect(body.idempotency_key.length).toBeGreaterThan(0);

    expect(readBankHandoff("TC-100")).toEqual({
      display: { Bank: "GTB", "Account number": "0011" },
      reference: "TC-100",
      instructions: "Use your order number.",
    });
    expect(sessionStorage.getItem("toke-coupon-code")).toBeNull();
  });

  it("shows a specific message and re-enables the button on a 409 idempotency conflict", async () => {
    mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "0.00", delivery: "5.00", tax: "0.00", grand_total: "25.00", currency: "GBP" }, coupon: { ok: true } },
      },
      [PLACE_URL]: { status: 409, body: { error: "idempotency_in_progress" } },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByText("£25.00")).toBeInTheDocument());
    const button = screen.getByRole("button", { name: /place order/i });
    fireEvent.click(button);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/still finishing your previous attempt/i));
    expect(button).not.toBeDisabled();
    expect(push).not.toHaveBeenCalled();
  });

  it("reuses the SAME idempotency_key on a retry after a lost-response failure — so the backend can replay the original order instead of orphaning it", async () => {
    // Simulates a network blip: the backend already created the order but the
    // response never made it back (a generic fetch rejection). The button
    // re-enables and the shopper clicks Place order again — that retry must carry
    // the identical key so the backend's idempotency layer replays the stored 201.
    const f = mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "0.00", delivery: "5.00", tax: "0.00", grand_total: "25.00", currency: "GBP" }, coupon: { ok: true } },
      },
      [PLACE_URL]: { status: 409, body: { error: "idempotency_in_progress" } },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByText("£25.00")).toBeInTheDocument());
    const button = screen.getByRole("button", { name: /place order/i });

    fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    fireEvent.click(button);
    await waitFor(() => expect(f.mock.calls.filter((c) => c[0] === PLACE_URL)).toHaveLength(2));

    const placeCalls = f.mock.calls.filter((c) => c[0] === PLACE_URL);
    const firstKey = JSON.parse((placeCalls[0][1] as RequestInit).body as string).idempotency_key;
    const secondKey = JSON.parse((placeCalls[1][1] as RequestInit).body as string).idempotency_key;
    expect(firstKey).toBe(secondKey);
    expect(typeof firstKey).toBe("string");
    expect(firstKey.length).toBeGreaterThan(0);
  });

  it("maps a CheckoutError (insufficient_stock) to a specific message with a cart link, button re-enabled", async () => {
    mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "0.00", delivery: "5.00", tax: "0.00", grand_total: "25.00", currency: "GBP" }, coupon: { ok: true } },
      },
      [PLACE_URL]: { status: 409, body: { error: "insufficient_stock", detail: "SKU1 has only 1 left." } },
    });

    renderHarness();

    await waitFor(() => expect(screen.getByText("£25.00")).toBeInTheDocument());
    const button = screen.getByRole("button", { name: /place order/i });
    fireEvent.click(button);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/no longer available/i));
    expect(screen.getByRole("link", { name: /review your bag/i })).toHaveAttribute("href", "/cart");
    expect(button).not.toBeDisabled();
  });

  it("reads the guest coupon-code stash into the quote request on mount", async () => {
    sessionStorage.setItem("toke-coupon-code", "WELCOME");
    const f = mockFetch({
      [QUOTE_URL]: {
        status: 200,
        body: { totals: { subtotal: "20.00", discount: "2.00", delivery: "5.00", tax: "0.00", grand_total: "23.00", currency: "GBP" }, coupon: { ok: true } },
      },
    });

    renderHarness();

    await waitFor(() => expect(f).toHaveBeenCalled());
    const [, init] = f.mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.coupon_code).toBe("WELCOME");
  });
});
