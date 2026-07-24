"use client";
import { useEffect, useState } from "react";
import { useCart } from "@/hooks/useCart";
import { onCartDrawerOpen } from "@/lib/cart-ui";
import { CartDrawer } from "@/components/layout/CartDrawer";

export function CartButton() {
  const [open, setOpen] = useState(false);
  const { cart } = useCart();
  useEffect(() => onCartDrawerOpen(() => setOpen(true)), []);
  const count = cart.items.reduce((n, l) => n + l.quantity, 0);
  return (
    <>
      <button onClick={() => setOpen(true)} className="relative" aria-label={`Bag, ${count} items`}>
        Bag
        {count > 0 && (
          <span className="absolute -right-3 -top-2 rounded-full bg-accent px-1.5 text-xs text-surface">
            {count}
          </span>
        )}
      </button>
      <CartDrawer open={open} onClose={() => setOpen(false)} />
    </>
  );
}
