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
 * ── IT FIRES ONLY WHEN THE MONEY HAS LANDED ─────────────────────────────────────────
 *
 * Added 2026-09-22, and it is a fix rather than a refinement. This component used to
 * fire on mount with no status check, and `ReviewStep` pushes a bank-transfer customer
 * straight here so they can read the account details — so the banner said "Your order is
 * reserved, complete your bank transfer" while the pixel reported a completed sale.
 * `isPaidStatus` is the gate; `lib/tracking/paid.ts` carries the argument AND the
 * measurement of how many orders this actually reached, which is smaller than the
 * expired-order count and worth reading before quoting a number.
 *
 * A customer who lands here unpaid and RETURNS once the transfer clears fires then: the
 * guard only records orders actually reported, so "not yet" stays retryable.
 *
 * ── THE EVENT ID IS THE ORDER NUMBER ────────────────────────────────────────────────
 *
 * Not a UUID, not a timestamp. It has to be a string that a webhook with no browser and
 * a browser with no webhook can both arrive at independently, and the order number is
 * the only such string. Change it here and every purchase is counted twice — which does
 * not look like a bug, it looks like a very good month.
 *
 * ── TWO GUARDS, NOT ONE ─────────────────────────────────────────────────────────────
 *
 * The four-platform fire and the Google Ads conversion take SEPARATE keys, because the
 * Google Ads conversion has a second surface that may also fire it
 * (`LateGoogleAdsConversion` on the account order page) and the four-platform fire does
 * not. Sharing one key would let whichever ran first silence the other.
 */
import { useEffect } from "react";
import { track, trackGoogleAdsConversion, type GoogleUserData } from "@/lib/tracking/events";
import { fireOnce, GOOGLE_ADS_KEY, PURCHASE_KEY } from "@/lib/tracking/once";
import { isPaidStatus } from "@/lib/tracking/paid";
import type { MarketingConfig } from "@/lib/marketing";
import type { OrderItem } from "@/lib/orders";

export function PurchaseTracker({
  orderNumber,
  status,
  currency,
  value,
  items,
  userData,
  config,
}: {
  orderNumber: string;
  /** The order's status. Nothing fires unless the money actually landed — see above. */
  status: string;
  currency: string;
  /** Goods after discounts, excluding shipping and tax — the SAME rule the server uses
   * (`apps/marketing/value.py`). Two halves of one event must not disagree about what
   * the sale was worth. */
  value: number;
  items: OrderItem[];
  /** Enhanced-conversions identifiers for Google only. The other three platforms take
   * their user data on the SERVER side, hashed, and are given none here. */
  userData?: GoogleUserData;
  config: MarketingConfig;
}) {
  useEffect(() => {
    if (!orderNumber || !isPaidStatus(status)) return;

    const tracked = items.map((item) => ({
      sku: item.sku,
      name: item.product_name,
      price: Number(item.unit_price),
      quantity: item.quantity,
    }));

    fireOnce(PURCHASE_KEY(orderNumber), () => {
      track({
        name: "purchase",
        eventId: orderNumber,
        currency,
        value,
        items: tracked,
        orderNumber,
      });
    });

    // Google Ads counts a conversion only when `send_to` names the conversion id AND its
    // label. The `purchase` event above reaches GA4 and is invisible to the ad account —
    // which is the usual reason a Google Ads conversion column reads zero while
    // analytics looks perfectly healthy.
    // `?? []` rather than `config.channels` directly: this component now renders on a
    // page customers open routinely, and an effect that THROWS in a client component
    // propagates to the nearest error boundary — i.e. a malformed config would take out
    // someone's order page to protect an ad pixel. The module's rule already: a pixel
    // must never break the shop.
    const ads = (config?.channels ?? []).find((c) => c.code === "google_ads");
    if (ads?.pixel_id && ads.secondary_id) {
      fireOnce(GOOGLE_ADS_KEY(orderNumber), () => {
        trackGoogleAdsConversion(ads.pixel_id, ads.secondary_id, {
          value, currency, orderNumber, userData,
        });
      });
    }
  }, [orderNumber, status, currency, value, items, userData, config]);

  return null;
}
