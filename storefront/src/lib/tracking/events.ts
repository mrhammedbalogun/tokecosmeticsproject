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
 * The identifiers Google matches a conversion against a signed-in Google account with —
 * "enhanced conversions for web" (added 2026-09-22).
 *
 * ── WHY UNHASHED, WHEN THE SERVER HALF HASHES EVERYTHING ────────────────────────────
 *
 * Because gtag normalises AND hashes these itself, in the browser, before anything
 * leaves the page — and its normalisation is the one Google actually matches against.
 * Pre-hashing here would mean reimplementing `channels/google_ads._google_email` in
 * TypeScript: strip the dots and the `+tag` from a gmail.com local part, but from no
 * other domain. Getting that subtly wrong produces a hash that matches nobody and
 * errors NOWHERE — the exact silent-failure shape that already cost this integration
 * nineteen dark days. Handing Google the raw value removes the whole class of bug.
 *
 * The values still only reach Google, over HTTPS, and only behind the consent gate that
 * decides whether gtag.js is on the page at all.
 */
export interface GoogleUserData {
  email?: string;
  /** E.164, with the leading `+`. Anything else is dropped rather than sent — Google
   * requires the format, and a malformed number is a wasted identifier, not an error. */
  phone?: string;
  firstName?: string;
  lastName?: string;
  street?: string;
  city?: string;
  region?: string;
  postcode?: string;
  /** ISO-3166-1 alpha-2. */
  country?: string;
}

const E164 = /^\+[1-9]\d{7,14}$/;

const clean = (value: string | undefined): string => (value ?? "").trim();

/**
 * Google's `user_data` object, or null when we hold nothing worth sending.
 *
 * The ADDRESS is all-or-nothing on its four identifying parts, which mirrors the server
 * adapter for the reason documented there: **most Nigerian addresses have no postcode**,
 * and a partial address is not a partial match, it is a worse one. Email and phone are
 * the stronger identifiers and carry the match alone.
 */
function googleUserDataPayload(data: GoogleUserData | undefined): Record<string, unknown> | null {
  if (!data) return null;
  const payload: Record<string, unknown> = {};

  const email = clean(data.email).toLowerCase();
  if (email.includes("@")) payload.email = email;

  // `replace` rather than a trim alone: a stored number is E.164 but a display copy of
  // it may have picked up spaces, and " +234 801..." is a format Google rejects whole.
  const phone = clean(data.phone).replace(/[\s()-]/g, "");
  if (E164.test(phone)) payload.phone_number = phone;

  const firstName = clean(data.firstName);
  const lastName = clean(data.lastName);
  const postcode = clean(data.postcode);
  const country = clean(data.country).toUpperCase().slice(0, 2);
  if (firstName && lastName && postcode && country.length === 2) {
    payload.address = {
      first_name: firstName,
      last_name: lastName,
      postal_code: postcode,
      country,
      ...(clean(data.street) ? { street: clean(data.street) } : {}),
      ...(clean(data.city) ? { city: clean(data.city) } : {}),
      ...(clean(data.region) ? { region: clean(data.region) } : {}),
    };
  }

  return Object.keys(payload).length > 0 ? payload : null;
}

/**
 * The Google Ads conversion, which is NOT a GA4 event and does not travel with one.
 *
 * Google Ads counts a conversion only when `send_to` names the conversion id AND its
 * label — the `AW-123456789/AbC-D_efG` pair. A `gtag("event", "purchase")` without it
 * reaches GA4 and is invisible to the ad account, which is the most common reason a
 * Google Ads conversion column reads zero while analytics looks healthy.
 *
 * ── `set` BEFORE `event`, NOT INSIDE IT ─────────────────────────────────────────────
 *
 * `gtag("set", "user_data", …)` is the shape Google documents for enhanced conversions,
 * and it must be queued BEFORE the conversion event so the tag has the identifiers when
 * it builds the hit. `dataLayer` is a plain array drained in order, so "before" here
 * means program order, not load order — the same property `TrackingScripts` relies on
 * for the consent default.
 *
 * Sending no `user_data` is not an error, it is just a conversion Google cannot enhance;
 * that was this integration's state until 2026-09-22, and it is what the account's
 * enhanced-conversions diagnostic was reporting as "No recent data / source: TAG".
 */
export function trackGoogleAdsConversion(
  conversionId: string,
  label: string,
  event: {
    value: number; currency: string; orderNumber?: string; userData?: GoogleUserData;
  },
): void {
  if (typeof window === "undefined" || !window.gtag || !conversionId || !label) return;
  try {
    const userData = googleUserDataPayload(event.userData);
    if (userData) window.gtag("set", "user_data", userData);
    window.gtag("event", "conversion", {
      send_to: `${conversionId}/${label}`,
      value: event.value,
      currency: event.currency,
      ...(event.orderNumber ? { transaction_id: event.orderNumber } : {}),
    });
  } catch { /* as above */ }
}
