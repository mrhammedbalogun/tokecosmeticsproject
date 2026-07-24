import { describe, it, expect, vi } from "vitest";
import { CART_OPEN_EVENT, openCartDrawer, onCartDrawerOpen } from "@/lib/cart-ui";

describe("cart-ui event bus", () => {
  it("openCartDrawer dispatches; onCartDrawerOpen subscribes and unsubscribes", () => {
    const cb = vi.fn();
    const off = onCartDrawerOpen(cb);
    openCartDrawer();
    expect(cb).toHaveBeenCalledTimes(1);
    off();
    openCartDrawer();
    expect(cb).toHaveBeenCalledTimes(1);
  });
  it("uses a namespaced event name", () => {
    expect(CART_OPEN_EVENT).toBe("toke:cart-open");
  });
});
