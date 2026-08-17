/** Where a coupon code waits between "typed in the cart" and "applied at checkout".
 *
 * A guest cannot validate a coupon (the quote endpoint is authed-only) and the cart
 * drawer has no totals panel to show a discount in, so both entry points stash the
 * raw code here and `ReviewStep` pre-fills and applies it. sessionStorage, not local:
 * a code is for this shopping session, not forever.
 *
 * Shared so the three call sites (CartView, CartDrawer, ReviewStep) cannot drift —
 * they used to each hold their own copy of the literal, which only works until one
 * of them is renamed. */
export const COUPON_STORAGE_KEY = "toke-coupon-code";

export function stashCoupon(code: string) {
  if (typeof sessionStorage !== "undefined") sessionStorage.setItem(COUPON_STORAGE_KEY, code);
}
