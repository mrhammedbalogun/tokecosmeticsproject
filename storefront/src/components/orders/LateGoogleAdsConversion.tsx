"use client";
/**
 * The Google Ads conversion, fired late — for the customer who never saw a paid
 * confirmation page (2026-09-22).
 *
 * ── THE GAP THIS FILLS ──────────────────────────────────────────────────────────────
 *
 * `PurchaseTracker` only fires when the order is already paid, and for the shop's main
 * payment method it usually is not: a bank-transfer customer reaches the confirmation
 * page seconds after PLACEMENT, hours before the transfer is reconciled. `CheckoutReturn`
 * gives up after 5 polls for the gateway methods. Either way the browser never gets a
 * chance to report a sale that really happened, and the account's enhanced-conversions
 * diagnostic reads "No recent data — source: TAG" no matter how good the server feed is.
 *
 * This is the second chance: the customer's own order page, which they reach from their
 * account after the email tells them payment cleared, by which time the status is
 * `processing`.
 *
 * ── WHY ONLY GOOGLE, AND NOT THE OTHER FOUR ─────────────────────────────────────────
 *
 * Because only Google's dedupe is reliable at this distance. Google matches on
 * `transaction_id` against the conversion action itself, and our server half has already
 * put the same order number there through Data Manager, so a late browser hit is folded
 * into the existing conversion rather than added to it — that is the documented Data
 * Manager behaviour the whole two-half design already rests on.
 *
 * Meta, TikTok and Snapchat dedupe on `event_id` only INSIDE their own short window.
 * `PurchaseTracker`'s own docstring names the consequence: "a refresh a week later lands
 * outside it". Firing those four here would turn one sale into two on three platforms to
 * improve measurement on a fourth. So they are not fired, and the four-platform key is
 * left untouched for a confirmation-page visit that may still happen.
 *
 * The key is shared with `PurchaseTracker`'s Google Ads fire, so whichever surface gets
 * there first is the only one that reports.
 */
import { useEffect } from "react";
import { trackGoogleAdsConversion, type GoogleUserData } from "@/lib/tracking/events";
import { fireOnce, GOOGLE_ADS_KEY } from "@/lib/tracking/once";
import { isPaidStatus } from "@/lib/tracking/paid";
import type { MarketingConfig } from "@/lib/marketing";

export function LateGoogleAdsConversion({
  orderNumber,
  status,
  currency,
  value,
  userData,
  config,
}: {
  orderNumber: string;
  status: string;
  currency: string;
  value: number;
  userData?: GoogleUserData;
  config: MarketingConfig;
}) {
  useEffect(() => {
    if (!orderNumber || !isPaidStatus(status)) return;
    // `?? []` rather than `config.channels` directly: this component now renders on a
    // page customers open routinely, and an effect that THROWS in a client component
    // propagates to the nearest error boundary — i.e. a malformed config would take out
    // someone's order page to protect an ad pixel. The module's rule already: a pixel
    // must never break the shop.
    const ads = (config?.channels ?? []).find((c) => c.code === "google_ads");
    if (!ads?.pixel_id || !ads.secondary_id) return;
    fireOnce(GOOGLE_ADS_KEY(orderNumber), () => {
      trackGoogleAdsConversion(ads.pixel_id, ads.secondary_id, {
        value, currency, orderNumber, userData,
      });
    });
  }, [orderNumber, status, currency, value, userData, config]);

  return null;
}
