/**
 * Fire something exactly once per order, per device — the guard both purchase surfaces
 * share (Plan-44).
 *
 * ── WHY `localStorage` AND NOT `sessionStorage` ─────────────────────────────────────
 *
 * The original guard was `sessionStorage`, and its own docstring named the hole it left:
 * "a refresh a week later lands outside it". That was tolerable while the confirmation
 * page was the only thing that ever fired, and it stopped being tolerable the moment a
 * SECOND surface could fire the same conversion (see `LateGoogleAdsConversion`) and the
 * moment the fire became conditional on a status that changes hours after the visit.
 *
 * Both of those turn "did this browser already report the order" into a question that
 * outlives the tab. `localStorage` answers it; `sessionStorage` cannot.
 *
 * ── THE KEY IS THE CONCERN, NOT THE PAGE ────────────────────────────────────────────
 *
 * Two keys exist per order: one for the four-platform fire, one for the Google Ads
 * conversion. They are separate because the Google Ads conversion has two surfaces that
 * may fire it and the four-platform fire has one — and they must not share a key, or
 * whichever ran first would suppress the other.
 *
 * Storage can throw (private mode, blocked site data) and can be wiped between visits.
 * A throw is treated as "not fired yet": an event the platform dedupes is a smaller
 * problem than a sale nobody reported, which is the same call the old guard made.
 */

export const PURCHASE_KEY = (orderNumber: string) => `tc_purchase_fired:${orderNumber}`;
export const GOOGLE_ADS_KEY = (orderNumber: string) => `tc_ads_fired:${orderNumber}`;

export function fireOnce(key: string, fire: () => void): void {
  if (typeof window === "undefined") return;
  let already = false;
  try {
    already = localStorage.getItem(key) !== null;
  } catch {
    // Storage unavailable. Fall through and fire — see the docstring.
  }
  if (already) return;
  try {
    localStorage.setItem(key, "1");
  } catch {
    // As above. The platforms' own id-based dedupe is the remaining net.
  }
  fire();
}
