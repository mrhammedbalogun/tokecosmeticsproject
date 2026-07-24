/** Micro event-bus so ANY island (PDP buy box, future quick-add) can open the
 * header's cart drawer without prop-drilling through the server layout. */
export const CART_OPEN_EVENT = "toke:cart-open";

export function openCartDrawer(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(CART_OPEN_EVENT));
}

export function onCartDrawerOpen(cb: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  const handler = () => cb();
  window.addEventListener(CART_OPEN_EVENT, handler);
  return () => window.removeEventListener(CART_OPEN_EVENT, handler);
}
