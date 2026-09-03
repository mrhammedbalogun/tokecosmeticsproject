"use client";
import { useEffect, useState } from "react";
import { useCart } from "@/hooks/useCart";
import { onCartDrawerOpen } from "@/lib/cart-ui";
import { CartDrawer } from "@/components/layout/CartDrawer";

/** Boutique shopping bag, drawn to match the site's line vocabulary (1.5 stroke,
 * round caps — same pen as the CategoryDropdown chevron). A bag, not a trolley:
 * this is a beauty counter, not a supermarket. */
function BagIcon() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className="h-[22px] w-[22px]"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M5.5 8.5h13l-.9 10.6a2 2 0 0 1-2 1.9H8.4a2 2 0 0 1-2-1.9L5.5 8.5Z" />
      <path d="M9 8.5V7a3 3 0 0 1 6 0v1.5" />
    </svg>
  );
}

export function CartButton() {
  const [open, setOpen] = useState(false);
  const { cart } = useCart();
  useEffect(() => onCartDrawerOpen(() => setOpen(true)), []);
  // Combo components count too. They live in `cart.combos[].items` and never in
  // `cart.items` (the two lists are disjoint by construction), so nothing is doubled.
  const count =
    cart.items.reduce((n, l) => n + l.quantity, 0) +
    (cart.combos ?? []).reduce(
      (n, c) => n + c.items.reduce((m, l) => m + l.quantity, 0),
      0,
    );
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        aria-label={`Cart, ${count} ${count === 1 ? "item" : "items"}`}
        className="relative inline-flex items-center justify-center p-1 transition-colors hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <BagIcon />
        {count > 0 && (
          <span
            aria-hidden
            className="absolute -right-1.5 -top-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold leading-none text-surface"
          >
            {count > 99 ? "99+" : count}
          </span>
        )}
      </button>
      <CartDrawer open={open} onClose={() => setOpen(false)} />
    </>
  );
}
