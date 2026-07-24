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
  it("shows the specific message for an invalid coupon", async () => {
    // initial mount quote (no coupon) is a guest 401, then the Apply-click quote returns invalid
    const f = vi.fn();
    f.mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Not authenticated." }), { status: 401 }));
    f.mockResolvedValueOnce(
      new Response(JSON.stringify({ totals: null, coupon: { ok: false, error_code: "not_found" } }), { status: 200 })
    );
    global.fetch = f as unknown as typeof fetch;

    render(<CartView />);
    const input = screen.getByLabelText(/coupon code/i);
    fireEvent.change(input, { target: { value: "BADCODE" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(screen.getByText(/isn't a valid code/i)).toBeInTheDocument());
  });

  it("shows a Discount row for a valid coupon", async () => {
    const f = vi.fn();
    f.mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Not authenticated." }), { status: 401 }));
    f.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          totals: {
            subtotal: "18500.00",
            discount: "5.00",
            delivery: "0.00",
            tax: "0.00",
            grand_total: "18495.00",
            currency: "NGN",
          },
          coupon: { ok: true },
        }),
        { status: 200 }
      )
    );
    global.fetch = f as unknown as typeof fetch;

    render(<CartView />);
    const input = screen.getByLabelText(/coupon code/i);
    fireEvent.change(input, { target: { value: "SAVE5" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(screen.getByText("Discount")).toBeInTheDocument());
  });

  it("stashes the code and shows the apply-at-checkout note for a guest", async () => {
    mockQuoteFetch(401, { detail: "Not authenticated." });

    render(<CartView />);
    const input = screen.getByLabelText(/coupon code/i);
    fireEvent.change(input, { target: { value: "GUESTCODE" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(screen.getByText(/apply your code at checkout/i)).toBeInTheDocument());
    expect(sessionStorage.getItem("toke-coupon-code")).toBe("GUESTCODE");
  });
});
