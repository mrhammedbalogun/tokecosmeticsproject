"use client";
/**
 * The browser half of the Purchase event (Plan-44).
 *
 * ── THIS IS THE HALF THAT IS ALLOWED TO GO MISSING ──────────────────────────────────
 *
 * The server half — `apps/marketing/events.enqueue_purchase`, fired from the paid
 * transition — is the one that must always happen. It runs off the gateway webhook, so
 * it reports a sale whether or not the customer ever comes back from Paystack.
 *
 * This one exists for the visitor who DOES come back, because a browser event carries
 * things a server event cannot: the vendor's own first-party cookie, the real client IP
 * and user agent, and the browsing session GA4 wants to join the purchase to. Where both
 * arrive, the platform keeps the browser one and discards the duplicate — which it can
 * only do because both send the same `event_id`.
 *
 * ── THE EVENT ID IS THE ORDER NUMBER ────────────────────────────────────────────────
 *
 * Not a UUID, not a timestamp. It has to be a string that a webhook with no browser and
 * a browser with no webhook can both arrive at independently, and the order number is
 * the only such string. Change it here and every purchase is counted twice — which does
 * not look like a bug, it looks like a very good month.
 *
 * ── FIRED ONCE PER MOUNT, GUARDED ───────────────────────────────────────────────────
 *
 * A confirmation page that a customer refreshes, or returns to from their email, would
 * otherwise re-report the sale. The platforms would dedupe it on the id — but only
 * inside their own window, and a refresh a week later lands outside it. `sessionStorage`
 * is the cheap guard that covers the case they will not.
 */
import { useEffect } from "react";
import { track, trackGoogleAdsConversion } from "@/lib/tracking/events";
import type { MarketingConfig } from "@/lib/marketing";
import type { OrderItem } from "@/lib/orders";

const FIRED_PREFIX = "tc_purchase_fired:";

export function PurchaseTracker({
  orderNumber,
  currency,
  value,
  items,
  config,
}: {
  orderNumber: string;
  currency: string;
  /** Goods after discounts, excluding shipping and tax — the SAME rule the server uses
   * (`apps/marketing/value.py`). Two halves of one event must not disagree about what
   * the sale was worth. */
  value: number;
  items: OrderItem[];
  config: MarketingConfig;
}) {
  useEffect(() => {
    if (!orderNumber) return;
    const key = `${FIRED_PREFIX}${orderNumber}`;
    try {
      if (sessionStorage.getItem(key)) return;
      sessionStorage.setItem(key, "1");
    } catch {
      // Private mode, or storage disabled. Fire anyway: an event the platform dedupes
      // is a smaller problem than a sale nobody reported.
    }

    const tracked = items.map((item) => ({
      sku: item.sku,
      name: item.product_name,
      price: Number(item.unit_price),
      quantity: item.quantity,
    }));

    track({
      name: "purchase",
      eventId: orderNumber,
      currency,
      value,
      items: tracked,
      orderNumber,
    });

    // Google Ads counts a conversion only when `send_to` names the conversion id AND its
    // label. The `purchase` event above reaches GA4 and is invisible to the ad account —
    // which is the usual reason a Google Ads conversion column reads zero while
    // analytics looks perfectly healthy.
    const ads = config.channels.find((c) => c.code === "google_ads");
    if (ads?.pixel_id && ads.secondary_id) {
      trackGoogleAdsConversion(ads.pixel_id, ads.secondary_id, {
        value, currency, orderNumber,
      });
    }
  }, [orderNumber, currency, value, items, config]);

  return null;
}
