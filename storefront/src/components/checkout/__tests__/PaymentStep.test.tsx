import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { CheckoutProvider, useCheckout } from "@/components/checkout/CheckoutContext";
import { PaymentStep } from "@/components/checkout/PaymentStep";
import type { Cart } from "@/lib/cart-types";

/** PaymentStep reads cart.country from useCart() — mock it the same way
 * DeliveryStep.test.tsx does so each test can pin the cart independently. */
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
    country: "NG",
    currency: "NGN",
    items: [{ id: 1, variant_id: 1, sku: "SKU1", name: "Item", variant_name: {}, quantity: 1, unit_price: "10.00", line_total: "10.00", unavailable: false }],
    subtotal: "10.00",
    has_unavailable: false,
    ...overrides,
  };
}

/** Small harness exposing completed/selections next to the real PaymentStep, mirroring
 * DeliveryStep.test.tsx's Harness. */
function Harness() {
  const { completed, selections } = useCheckout();
  return (
    <div>
      <p data-testid="completed">{[...completed].sort().join(",")}</p>
      <p data-testid="paymentGateway">{selections.paymentGateway ?? ""}</p>
      <PaymentStep />
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

function mockFetch(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } })
  );
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

describe("PaymentStep", () => {
  it("renders bank_transfer with its label + note", async () => {
    const f = mockFetch(200, [{ gateway: "bank_transfer", sort_order: 1 }]);
    renderHarness();

    await waitFor(() => expect(screen.getByText("Bank transfer")).toBeInTheDocument());
    expect(screen.getByText(/pay by transfer/i)).toBeInTheDocument();

    const url = (f.mock.calls[0][0] as string).toString();
    expect(url).toContain("/api/checkout/payment-methods");
    expect(url).toContain("country=NG");
  });

  it("selecting bank_transfer completes step 4 with paymentGateway: bank_transfer", async () => {
    mockFetch(200, [{ gateway: "bank_transfer", sort_order: 1 }]);
    renderHarness();

    await waitFor(() => expect(screen.getByText("Bank transfer")).toBeInTheDocument());
    const card = screen.getByText("Bank transfer").closest("[role='radio']")!;
    fireEvent.click(card);

    await waitFor(() => expect(screen.getByTestId("completed")).toHaveTextContent("4"));
    expect(screen.getByTestId("paymentGateway")).toHaveTextContent("bank_transfer");
  });

  it("shows a no-methods message when the list is empty", async () => {
    mockFetch(200, []);
    renderHarness();

    await waitFor(() =>
      expect(screen.getByText(/no payment methods available for your region/i)).toBeInTheDocument()
    );
  });

  it("shows a retry note on fetch error instead of crashing", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("network down")) as unknown as typeof fetch;
    renderHarness();

    await waitFor(() =>
      expect(screen.getByText(/couldn't load payment methods/i)).toBeInTheDocument()
    );
  });
});
