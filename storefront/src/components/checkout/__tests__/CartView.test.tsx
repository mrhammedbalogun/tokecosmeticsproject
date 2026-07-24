import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { CartView } from "@/components/checkout/CartView";
import type { Cart } from "@/lib/cart-types";

const setQtyMutate = vi.fn();
let mockCart: Cart;

vi.mock("@/hooks/useCart", () => ({
  useCart: () => ({
    cart: mockCart,
    isLoading: false,
    addItem: { mutate: vi.fn() },
    setQty: { mutate: setQtyMutate },
  }),
}));

function makeCart(overrides: Partial<Cart> = {}): Cart {
  return {
    id: "cart-1",
    kind: "standard",
    status: "active",
    country: "NG",
    currency: "NGN",
    items: [
      {
        id: 1,
        variant_id: 10,
        sku: "TOKE-SERUM-50",
        name: "Radiance Glow Serum",
        variant_name: { size: "50ml" },
        quantity: 2,
        unit_price: "9250.00",
        line_total: "18500.00",
        unavailable: false,
      },
    ],
    subtotal: "18500.00",
    has_unavailable: false,
    ...overrides,
  };
}

const originalFetch = global.fetch;

beforeEach(() => {
  mockCart = makeCart();
  setQtyMutate.mockClear();
  sessionStorage.clear();
});

afterEach(() => {
  global.fetch = originalFetch;
  vi.restoreAllMocks();
});

function mockQuoteFetch(status: number, body: unknown) {
  const f = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } })
  );
  global.fetch = f as unknown as typeof fetch;
  return f;
}

describe("CartView", () => {
  it("renders subtotal-only on initial load, with no coupon quote fetched and no coupon message shown", () => {
    const f = vi.fn();
    global.fetch = f as unknown as typeof fetch;

    render(<CartView />);

    expect(screen.getByText("Delivery & taxes calculated at checkout.")).toBeInTheDocument();
    expect(screen.queryByText(/isn't a valid code/i)).toBeNull();
    expect(screen.queryByText(/apply your code at checkout/i)).toBeNull();
    expect(screen.queryByText(/couldn.t apply/i)).toBeNull();
    // No quote request until the shopper explicitly clicks Apply.
    expect(f).not.toHaveBeenCalled();
  });

  it("shows the specific message for an invalid coupon (Apply-click only)", async () => {
    const f = mockQuoteFetch(200, { totals: null, coupon: { ok: false, error_code: "not_found" } });

    render(<CartView />);
    const input = screen.getByLabelText(/coupon code/i);
    fireEvent.change(input, { target: { value: "BADCODE" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(screen.getByText(/isn't a valid code/i)).toBeInTheDocument());
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("shows a Discount row for a valid coupon (Apply-click only)", async () => {
    const f = mockQuoteFetch(200, {
      totals: {
        subtotal: "18500.00",
        discount: "5.00",
        delivery: "0.00",
        tax: "0.00",
        grand_total: "18495.00",
        currency: "NGN",
      },
      coupon: { ok: true },
    });

    render(<CartView />);
    const input = screen.getByLabelText(/coupon code/i);
    fireEvent.change(input, { target: { value: "SAVE5" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(screen.getByText("Discount")).toBeInTheDocument());
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("stashes the code and shows the apply-at-checkout note for a guest", async () => {
    const f = mockQuoteFetch(401, { detail: "Not authenticated." });

    render(<CartView />);
    const input = screen.getByLabelText(/coupon code/i);
    fireEvent.change(input, { target: { value: "GUESTCODE" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(screen.getByText(/apply your code at checkout/i)).toBeInTheDocument());
    expect(sessionStorage.getItem("toke-coupon-code")).toBe("GUESTCODE");
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("drops back to subtotal-only after a qty change following a successful coupon apply", async () => {
    mockQuoteFetch(200, {
      totals: {
        subtotal: "18500.00",
        discount: "5.00",
        delivery: "0.00",
        tax: "0.00",
        grand_total: "18495.00",
        currency: "NGN",
      },
      coupon: { ok: true },
    });

    render(<CartView />);
    const input = screen.getByLabelText(/coupon code/i);
    fireEvent.change(input, { target: { value: "SAVE5" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));
    await waitFor(() => expect(screen.getByText("Discount")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /increase quantity/i }));

    expect(setQtyMutate).toHaveBeenCalledWith({ variantId: 10, quantity: 3 });
    expect(screen.queryByText("Discount")).toBeNull();
    expect(screen.getByText("Delivery & taxes calculated at checkout.")).toBeInTheDocument();
  });
});
