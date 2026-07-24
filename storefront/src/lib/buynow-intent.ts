/** Buy-Now guest-resume intent (stashed by the PDP when a logged-out shopper clicks Buy Now). */
export const BUYNOW_INTENT_KEY = "toke-buynow-intent";
export interface BuyNowIntent { variant_id: number; quantity: number }

export function readBuyNowIntent(): BuyNowIntent | null {
  if (typeof sessionStorage === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(BUYNOW_INTENT_KEY);
    if (!raw) return null;
    const v = JSON.parse(raw);
    if (typeof v?.variant_id === "number" && typeof v?.quantity === "number") return v;
    return null;
  } catch { return null; }
}
export function clearBuyNowIntent(): void {
  if (typeof sessionStorage !== "undefined") sessionStorage.removeItem(BUYNOW_INTENT_KEY);
}
