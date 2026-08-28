import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { CartDrawer } from "@/components/layout/CartDrawer";
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
        image: "https://cdn.example/catalog/thumbs/serum.jpg",
        product_slug: "radiance-glow-serum",
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

beforeEach(() => {
  mockCart = makeCart();
  setQtyMutate.mockClear();
  sessionStorage.clear();
});

describe("CartDrawer", () => {
  it("shows the product picture, options and a total item count", () => {
    render(<CartDrawer open onClose={vi.fn()} />);

    expect(screen.getByRole("heading", { name: /Review Your Cart \(2\)/ })).toBeInTheDocument();
    // The thumbnail is decorative (alt=""), so it is queried as an image with no
    // accessible name. next/image rewrites src through the optimizer — assert the
    // encoded original survives rather than an exact URL.
    const img = document.querySelector("img") as HTMLImageElement;
    expect(img.alt).toBe("");
    expect(decodeURIComponent(img.src)).toContain("catalog/thumbs/serum.jpg");
    expect(screen.getByText("50ml")).toBeInTheDocument();
  });

  it("links the line to its product page", () => {
    render(<CartDrawer open onClose={vi.fn()} />);
    expect(screen.getByRole("link", { name: "Radiance Glow Serum" })).toHaveAttribute(
      "href",
      "/product/radiance-glow-serum",
    );
  });

  it("steps quantity and removes", () => {
    render(<CartDrawer open onClose={vi.fn()} />);

    fireEvent.click(screen.getByLabelText("Increase quantity of Radiance Glow Serum"));
    expect(setQtyMutate).toHaveBeenCalledWith({ variantId: 10, quantity: 3 });

    fireEvent.click(screen.getByLabelText("Remove Radiance Glow Serum"));
    expect(setQtyMutate).toHaveBeenCalledWith({ variantId: 10, quantity: 0 });
  });

  it("stashes a discount code for checkout instead of validating it here", () => {
    render(<CartDrawer open onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /Got a discount code\?/ }));
    fireEvent.change(screen.getByLabelText("Discount code"), { target: { value: "SAVE10" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(sessionStorage.getItem("toke-coupon-code")).toBe("SAVE10");
    expect(screen.getByText(/apply it at checkout/i)).toBeInTheDocument();
  });

  it("takes a referral code, so the fastest route to checkout is not the one that hides it", async () => {
    // This drawer's Checkout button goes straight to /checkout. Before 2026-08-28 the
    // referral field existed only on /cart and at the review step, so the two quickest
    // paths to payment — "Buy now" and this button — skipped every chance to enter a
    // code until the very last screen.
    const f = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ valid: true, referrer_name: "Amina", customer_discount_percent: "5.00" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    const originalFetch = global.fetch;
    global.fetch = f as unknown as typeof fetch;
    try {
      render(<CartDrawer open onClose={vi.fn()} />);

      // Collapsed here, unlike the review step: the drawer is a browsing surface, and an
      // open box asking for a code invites a shopper without one to go hunting.
      fireEvent.click(screen.getByRole("button", { name: /Have a friend.s referral code\?/ }));
      fireEvent.change(screen.getByLabelText(/Friend.s referral code/), {
        target: { value: "amina7k3p" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Apply" }));

      expect(await screen.findByText(/Amina.s link/)).toBeInTheDocument();
      expect(f).toHaveBeenCalledWith("/api/referral", expect.objectContaining({ method: "POST" }));
    } finally {
      global.fetch = originalFetch;
    }
  });

  it("gives the drawer's referral input its own id, since /cart renders one too", () => {
    // The drawer lives in the layout and stays mounted behind /cart. A shared
    // id="referral-code" would put two in one document and point the cart page's <label>
    // at this hidden input — the same reason the coupon boxes are namespaced.
    render(<CartDrawer open onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: /Have a friend.s referral code\?/ }));
    expect(screen.getByLabelText(/Friend.s referral code/)).toHaveAttribute(
      "id",
      "referral-code-drawer",
    );
  });

  it("Continue Shopping and Escape both close the drawer", () => {
    const onClose = vi.fn();
    render(<CartDrawer open onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Continue Shopping" }));
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("shows a checkout button carrying the subtotal", () => {
    render(<CartDrawer open onClose={vi.fn()} />);
    const checkout = screen.getByRole("link", { name: /Checkout/ });
    expect(checkout).toHaveAttribute("href", "/checkout");
    expect(within(checkout).getByText("₦18,500.00")).toBeInTheDocument();
  });

  it("empty cart offers a way back to the shop and hides the footer", () => {
    mockCart = makeCart({ items: [], subtotal: "0.00" });
    render(<CartDrawer open onClose={vi.fn()} />);

    expect(screen.getByText("Your cart is empty.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start shopping" })).toHaveAttribute("href", "/products");
    expect(screen.queryByRole("link", { name: /Checkout/ })).not.toBeInTheDocument();
  });

  it("an unavailable line says so and offers removal, with no stepper", () => {
    mockCart = makeCart({
      items: [{ ...makeCart().items[0], unavailable: true, unit_price: null, line_total: null }],
      subtotal: "0.00",
      has_unavailable: true,
    });
    render(<CartDrawer open onClose={vi.fn()} />);

    expect(screen.getByText("No longer available")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Increase quantity/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Remove Radiance Glow Serum")).toBeInTheDocument();
  });

  it("renders a line with no picture or slug without crashing", () => {
    mockCart = makeCart({
      items: [{ ...makeCart().items[0], image: null, product_slug: undefined }],
    });
    render(<CartDrawer open onClose={vi.fn()} />);

    expect(screen.getByText("Radiance Glow Serum")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Radiance Glow Serum" })).not.toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });
});
