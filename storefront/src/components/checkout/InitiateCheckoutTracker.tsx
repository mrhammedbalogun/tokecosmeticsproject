"use client";
/**
 * Fires InitiateCheckout once, when a real cart reaches the checkout page (Plan-44).
 *
 * ── ONCE PER CART, NOT ONCE PER RENDER ──────────────────────────────────────────────
 *
 * `CheckoutFlow` re-renders on every step of the five-step machine and on every cart
 * mutation inside it. Firing on each would report a customer who edited their address as
 * five people starting a checkout, and InitiateCheckout is an event the ad platforms
 * optimise delivery against — inflating it teaches them to find browsers rather than
 * buyers. The cart id is the natural once-key: a new cart is a new checkout.
 *
 * ── VALUE IS THE CART SUBTOTAL, WHICH IS DELIBERATE ─────────────────────────────────
 *
 * Delivery has not been chosen yet at this point, and neither has a coupon. The subtotal
 * is the only number that exists, and it is the same basis the Purchase event uses
 * (goods, excluding freight) — so the funnel's two ends are measured the same way.
 */
import { useEffect, useRef } from "react";
import type { Cart } from "@/lib/cart-types";
import { newEventId, track } from "@/lib/tracking/events";

export function InitiateCheckoutTracker({ cart }: { cart: Cart }) {
  const firedFor = useRef<string>("");

  useEffect(() => {
    if (!cart.id || cart.items.length === 0) return;
    if (firedFor.current === cart.id) return;
    firedFor.current = cart.id;

    track({
      name: "initiate_checkout",
      eventId: newEventId(),
      currency: cart.currency,
      value: Number(cart.subtotal || 0),
      items: cart.items
        .filter((line) => !line.unavailable && line.unit_price)
        .map((line) => ({
          sku: line.sku,
          name: line.name,
          price: Number(line.unit_price),
          quantity: line.quantity,
        })),
    });
  }, [cart]);

  return null;
}
