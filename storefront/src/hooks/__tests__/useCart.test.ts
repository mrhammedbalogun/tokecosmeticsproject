import { describe, it, expect } from "vitest";
import { applyOptimisticQty } from "@/hooks/useCart";
import type { Cart } from "@/lib/cart-types";

const cart: Cart = {
  id: "c1", kind: "standard", status: "active", country: "NG", currency: "NGN",
  items: [
    { id: 1, variant_id: 10, sku: "A", name: "A", variant_name: {}, quantity: 2, unit_price: "100.00", line_total: "200.00", unavailable: false },
  ],
  subtotal: "200.00", has_unavailable: false,
};

describe("applyOptimisticQty", () => {
  it("updates a line quantity and recomputes its line total + subtotal", () => {
    const next = applyOptimisticQty(cart, 10, 3);
    expect(next.items[0].quantity).toBe(3);
    expect(next.items[0].line_total).toBe("300.00");
    expect(next.subtotal).toBe("300.00");
  });

  it("removes the line when quantity hits 0", () => {
    const next = applyOptimisticQty(cart, 10, 0);
    expect(next.items).toHaveLength(0);
    expect(next.subtotal).toBe("0.00");
  });

  it("is a no-op for an unknown variant", () => {
    const next = applyOptimisticQty(cart, 999, 5);
    expect(next.items[0].quantity).toBe(2);
  });
});
