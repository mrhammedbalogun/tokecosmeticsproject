import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useEffect } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { CheckoutProvider, useCheckout } from "@/components/checkout/CheckoutContext";
import { DeliveryStep } from "@/components/checkout/DeliveryStep";
import type { Cart } from "@/lib/cart-types";

/** DeliveryStep reads cart.id/cart.currency from useCart() — mock it the same way
 * AddressStep.test.tsx does so each test can pin the cart independently. */
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
    items: [{ id: 1, variant_id: 1, sku: "SKU1", name: "Item", variant_name: {}, quantity: 1, unit_price: "10.00", line_total: "10.00", unavailable: false }],
    subtotal: "10.00",
    has_unavailable: false,
    ...overrides,
  };
}

/** Small harness that seeds selections.addressId (mirroring what AddressStep would
 * have already done in step 2) via a one-shot mount effect, then renders the real
 * DeliveryStep next to the checkout machine's completed/selections state. */
function Harness({ addressId }: { addressId?: number }) {
  const { completed, selections, setAddress } = useCheckout();
  useEffect(() => {
    if (addressId !== undefined) setAddress(addressId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div>
      <p data-testid="completed">{[...completed].sort().join(",")}</p>
      <p data-testid="deliveryOptionId">{String(selections.deliveryOptionId ?? "")}</p>
      <p data-testid="deliveryDisplay">{selections.deliveryDisplay ?? ""}</p>
      <DeliveryStep />
    </div>
  );
}

function renderHarness(addressId?: number) {
  return render(
    <CheckoutProvider>
      <Harness addressId={addressId} />
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

describe("DeliveryStep", () => {
  it("shows a muted message when no address has been chosen yet", () => {
    renderHarness(undefined);
    expect(screen.getByText(/choose a delivery address first/i)).toBeInTheDocument();
  });

  it("fetches and renders options as cards with formatted price + ETA", async () => {
    const f = mockFetch(200, [
      { id: 1, name: "Standard", price: "5.00", eta_min_days: 2, eta_max_days: 4, quote_required: false },
      { id: 2, name: "Express", price: "12.50", eta_min_days: 1, eta_max_days: 1, quote_required: false },
    ]);
    renderHarness(7);

    await waitFor(() => expect(screen.getByText("Standard")).toBeInTheDocument());
    expect(screen.getByText("£5.00")).toBeInTheDocument();
    expect(screen.getByText("2–4 days")).toBeInTheDocument();
    expect(screen.getByText("Express")).toBeInTheDocument();
    expect(screen.getByText("£12.50")).toBeInTheDocument();
    expect(screen.getByText("1 days")).toBeInTheDocument();

    const url = (f.mock.calls[0][0] as string).toString();
    expect(url).toContain("/api/checkout/delivery-options");
    expect(url).toContain("address_id=7");
    expect(url).toContain("cart_id=cart-1");
  });

  it("selecting an option completes step 3 with the right deliveryOptionId", async () => {
    mockFetch(200, [
      { id: 1, name: "Standard", price: "5.00", eta_min_days: 2, eta_max_days: 4, quote_required: false },
    ]);
    renderHarness(7);

    await waitFor(() => expect(screen.getByText("Standard")).toBeInTheDocument());
    const card = screen.getByText("Standard").closest("[role='radio']")!;
    fireEvent.click(card);

    await waitFor(() => expect(screen.getByTestId("completed")).toHaveTextContent("3"));
    expect(screen.getByTestId("deliveryOptionId")).toHaveTextContent("1");
    expect(screen.getByTestId("deliveryDisplay")).toHaveTextContent("Standard");
  });

  it("shows 'Quoted after checkout' for a quote_required option and it is still selectable", async () => {
    mockFetch(200, [
      { id: 3, name: "International Freight", price: null, eta_min_days: 10, eta_max_days: 20, quote_required: true },
    ]);
    renderHarness(9);

    await waitFor(() => expect(screen.getByText("International Freight")).toBeInTheDocument());
    expect(screen.getByText("Quoted after checkout")).toBeInTheDocument();

    const card = screen.getByText("International Freight").closest("[role='radio']")!;
    fireEvent.click(card);

    await waitFor(() => expect(screen.getByTestId("completed")).toHaveTextContent("3"));
    expect(screen.getByTestId("deliveryOptionId")).toHaveTextContent("3");
  });

  it("shows a no-options message when the list is empty", async () => {
    mockFetch(200, []);
    renderHarness(7);

    await waitFor(() =>
      expect(screen.getByText(/no delivery options for this address/i)).toBeInTheDocument()
    );
  });

  it("shows a retry note on fetch error instead of crashing", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("network down")) as unknown as typeof fetch;
    renderHarness(7);

    await waitFor(() =>
      expect(screen.getByText(/couldn't load delivery options/i)).toBeInTheDocument()
    );
  });
});
