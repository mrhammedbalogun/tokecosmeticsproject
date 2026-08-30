/**
 * The browser-side event vocabulary, translated once per platform (Plan-44).
 *
 * The mirror image of `apps/marketing/payloads.py` on the server: ONE canonical event
 * shape, four vendor spellings. Keeping the translation in one file rather than at each
 * call site is what stops a product page sending TikTok's spelling to Snapchat.
 *
 * ── THE `eventId` IS THE WHOLE DEDUPLICATION STORY ──────────────────────────────────
 *
 * Every platform here dedupes a browser event against a server event by matching the id.
 * For a purchase it is the ORDER NUMBER, which both halves know without having to talk
 * to each other — the server reads it off the order, the confirmation page has it in the
 * URL. Get this wrong and every sale is counted twice, which does not look like a bug;
 * it looks like a very good month.
 *
 * For the top-of-funnel events there is no server half today, so the id only has to be
 * unique. It is generated per fire.
 */

export interface TrackedItem {
  /** The SKU. The product feed, the pixel and the server-side event must all name a
   * product the same way or dynamic retargeting silently shows nothing. */
  sku: string;
  name?: string;
  price: number;
  quantity: number;
}

export interface TrackedEvent {
  name: "view_content" | "add_to_cart" | "initiate_checkout" | "purchase";
  eventId: string;
  currency: string;
  value: number;
  items: TrackedItem[];
  orderNumber?: string;
}

declare global {
  interface Window {
    fbq?: (...args: unknown[]) => void;
    ttq?: { track: (event: string, params?: unknown, options?: unknown) => void };
    snaptr?: (...args: unknown[]) => void;
    gtag?: (...args: unknown[]) => void;
    dataLayer?: unknown[];
  }
}

/** A random id for the events that have no server half to agree with. */
export function newEventId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

const META_NAMES: Record<TrackedEvent["name"], string> = {
  view_content: "ViewContent",
  add_to_cart: "AddToCart",
  initiate_checkout: "InitiateCheckout",
  purchase: "Purchase",
};

const TIKTOK_NAMES: Record<TrackedEvent["name"], string> = {
  view_content: "ViewContent",
  add_to_cart: "AddToCart",
  initiate_checkout: "InitiateCheckout",
  // CompletePayment, not PlaceAnOrder: ours fires when the money is taken.
  purchase: "CompletePayment",
};

const SNAP_NAMES: Record<TrackedEvent["name"], string> = {
  view_content: "VIEW_CONTENT",
  add_to_cart: "ADD_CART",   // not ADD_TO_CART — Snap's own spelling
  initiate_checkout: "START_CHECKOUT",
  purchase: "PURCHASE",
};

const GA4_NAMES: Record<TrackedEvent["name"], string> = {
  view_content: "view_item",
  add_to_cart: "add_to_cart",
  initiate_checkout: "begin_checkout",
  purchase: "purchase",
};

/**
 * Fire one event at every pixel that is loaded.
 *
 * Each call is guarded on the global existing, because "loaded" is not something this
 * module can know: a channel may be switched off in the admin, an ad blocker may have
 * eaten the script, or consent may have been withdrawn since the page rendered. A
 * missing global is the normal case, not an error, and it must never throw into a click
 * handler on the add-to-cart button.
 */
export function track(event: TrackedEvent): void {
  if (typeof window === "undefined") return;
  const skus = event.items.map((i) => i.sku);

  try {
    window.fbq?.("track", META_NAMES[event.name], {
      currency: event.currency,
      value: event.value,
      content_type: "product",
      content_ids: skus,
      contents: event.items.map((i) => ({
        id: i.sku, quantity: i.quantity, item_price: i.price,
      })),
      ...(event.orderNumber ? { order_id: event.orderNumber } : {}),
    }, { eventID: event.eventId });
  } catch { /* a pixel must never break the shop */ }

  try {
    window.ttq?.track(TIKTOK_NAMES[event.name], {
      currency: event.currency,
      value: event.value,
      contents: event.items.map((i) => ({
        content_id: i.sku, content_type: "product",
        content_name: i.name ?? i.sku, quantity: i.quantity, price: i.price,
      })),
      ...(event.orderNumber ? { order_id: event.orderNumber } : {}),
    }, { event_id: event.eventId });
  } catch { /* as above */ }

  try {
    window.snaptr?.("track", SNAP_NAMES[event.name], {
      currency: event.currency,
      // Snap wants a string here, exactly as its Conversions API does.
      price: String(event.value),
      item_ids: skus,
      number_items: event.items.reduce((sum, i) => sum + i.quantity, 0),
      ...(event.orderNumber ? { transaction_id: event.orderNumber } : {}),
      client_dedup_id: event.eventId,
    });
  } catch { /* as above */ }

  try {
    window.gtag?.("event", GA4_NAMES[event.name], {
      currency: event.currency,
      value: event.value,
      ...(event.orderNumber ? { transaction_id: event.orderNumber } : {}),
      items: event.items.map((i) => ({
        item_id: i.sku, item_name: i.name ?? i.sku, price: i.price, quantity: i.quantity,
      })),
    });
  } catch { /* as above */ }
}

/**
 * The Google Ads conversion, which is NOT a GA4 event and does not travel with one.
 *
 * Google Ads counts a conversion only when `send_to` names the conversion id AND its
 * label — the `AW-123456789/AbC-D_efG` pair. A `gtag("event", "purchase")` without it
 * reaches GA4 and is invisible to the ad account, which is the most common reason a
 * Google Ads conversion column reads zero while analytics looks healthy.
 */
export function trackGoogleAdsConversion(
  conversionId: string,
  label: string,
  event: { value: number; currency: string; orderNumber?: string },
): void {
  if (typeof window === "undefined" || !window.gtag || !conversionId || !label) return;
  try {
    window.gtag("event", "conversion", {
      send_to: `${conversionId}/${label}`,
      value: event.value,
      currency: event.currency,
      ...(event.orderNumber ? { transaction_id: event.orderNumber } : {}),
    });
  } catch { /* as above */ }
}
