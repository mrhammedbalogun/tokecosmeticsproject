import { describe, it, expect } from "vitest";
import { applyOptimisticComboQty } from "@/hooks/useCart";
import type { Cart } from "@/lib/cart-types";

/** One bundle (₦1,800 each, ₦2,000 of parts) alongside one standalone ₦500 line. */
const cart: Cart = {
  id: "c1", kind: "standard", status: "active", country: "NG", currency: "NGN",
  items: [
    {
      id: 9, variant_id: 99, sku: "S", name: "Standalone", variant_name: {},
      quantity: 1, unit_price: "500.00", line_total: "500.00", unavailable: false,
    },
  ],
  combos: [
    {
      group_id: 1,
      combo_slug: "glow-kit",
      name: "Glow Kit",
      quantity: 1,
      unit_price: "1800.00",
      line_total: "1800.00",
      components_total: "2000.00",
      saving: "200.00",
      unavailable: false,
      items: [
        {
          id: 1, variant_id: 10, sku: "A", name: "A", variant_name: {},
          quantity: 1, unit_price: "1000.00", line_total: "1000.00", unavailable: false,
        },
        {
          id: 2, variant_id: 11, sku: "B", name: "B", variant_name: {},
          quantity: 2, unit_price: "500.00", line_total: "1000.00", unavailable: false,
        },
      ],
    },
  ],
  subtotal: "2500.00", combo_discount: "200.00", total: "2300.00", has_unavailable: false,
};

describe("applyOptimisticComboQty", () => {
  it("scales the bundle, its saving, and the money", () => {
    const next = applyOptimisticComboQty(cart, 1, 3);
    const combo = next.combos![0];
    expect(combo.quantity).toBe(3);
    expect(combo.line_total).toBe("5400.00");
    expect(combo.components_total).toBe("6000.00");
    expect(combo.saving).toBe("600.00");
    // 500 standalone + 6,000 of parts
    expect(next.subtotal).toBe("6500.00");
    expect(next.combo_discount).toBe("600.00");
    expect(next.total).toBe("5900.00");
  });

  it("scales the component rows by their per-box quantities", () => {
    // A card whose header says 3 over rows still saying 1 is worse than no optimism.
    // The per-box figures are recovered exactly, the way the server derives them.
    const combo = applyOptimisticComboQty(cart, 1, 3).combos![0];
    expect(combo.items.map((l) => l.quantity)).toEqual([3, 6]);
    expect(combo.items.map((l) => l.line_total)).toEqual(["3000.00", "3000.00"]);
  });

  it("removes the whole group at zero — a combo is bought whole", () => {
    const next = applyOptimisticComboQty(cart, 1, 0);
    expect(next.combos).toHaveLength(0);
    expect(next.subtotal).toBe("500.00");
    expect(next.combo_discount).toBe("0.00");
    expect(next.total).toBe("500.00");
  });

  it("is a no-op for an unknown group", () => {
    const next = applyOptimisticComboQty(cart, 999, 5);
    expect(next.combos![0].quantity).toBe(1);
    expect(next.total).toBe("2300.00");
  });

  it("an ENDED bundle still counts its goods, and earns nothing", () => {
    // The deal lapsed; the products did not, and the till still charges for them. A
    // subtotal that dropped them would show goods as free.
    const ended: Cart = {
      ...cart,
      combos: [
        {
          ...cart.combos![0],
          ended: true,
          saving: "0.00",
          unit_price: null,
          line_total: "2000.00",
          components_total: "2000.00",
        },
      ],
      subtotal: "2500.00",
      combo_discount: "0.00",
      total: "2500.00",
    };
    const next = applyOptimisticComboQty(ended, 999, 1);
    expect(next.subtotal).toBe("2500.00");
    expect(next.combo_discount).toBe("0.00");
    expect(next.total).toBe("2500.00");
  });

  it("leaves a genuinely unavailable bundle out of every total", () => {
    // `unavailable` is the harder state: a COMPONENT cannot be priced here at all, so
    // there is no number to count.
    const lapsed: Cart = {
      ...cart,
      combos: [{ ...cart.combos![0], unavailable: true, saving: null, components_total: null }],
    };
    const next = applyOptimisticComboQty(lapsed, 999, 1);
    expect(next.subtotal).toBe("500.00");
    expect(next.combo_discount).toBe("0.00");
  });
});
