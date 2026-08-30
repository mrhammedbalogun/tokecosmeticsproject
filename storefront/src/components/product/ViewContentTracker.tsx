"use client";
/**
 * Fires ViewContent when a product page is opened (Plan-44).
 *
 * A mount-effect component in the shape of `RecentlyViewedTracker` next door, and it
 * lives in the tree rather than inside `BuyBox` for the same reason that one does: the
 * PDP is a server component, this is one client island with one job, and it renders
 * nothing.
 *
 * ── WHY IT NEEDS NO CONSENT CHECK ───────────────────────────────────────────────────
 *
 * `track()` calls each vendor through its own global (`window.fbq`, `window.ttq`, …),
 * and those globals only exist because `TrackingScripts` injected the script, which it
 * only does when consent allows. A visitor who refused has no globals, so every call is
 * a no-op. Adding a second consent check here would be a second place for the rule to
 * be wrong.
 *
 * The exception is Google, whose tag IS loaded for a refusing visitor — deliberately,
 * because Consent Mode wants to be told about the refusal rather than not exist. gtag
 * itself then drops what it may not record.
 */
import { useEffect } from "react";
import { newEventId, track } from "@/lib/tracking/events";

export function ViewContentTracker({
  sku,
  name,
  price,
  currency,
}: {
  sku: string;
  name: string;
  price: number;
  currency: string;
}) {
  useEffect(() => {
    if (!sku || !currency) return;
    track({
      name: "view_content",
      eventId: newEventId(),
      currency,
      value: price,
      items: [{ sku, name, price, quantity: 1 }],
    });
  }, [sku, name, price, currency]);
  return null;
}
