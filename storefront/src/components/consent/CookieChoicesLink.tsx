"use client";
/**
 * The footer's "Cookie choices" link — the withdrawal route.
 *
 * A link rather than a page, because reopening the banner puts the visitor in front of
 * the exact controls they used the first time. A separate preferences page would be a
 * second implementation of the same three switches, and the second one is the one that
 * goes out of date.
 *
 * Renders nothing when tracking is switched off store-wide: a "cookie choices" link that
 * opens a banner about cookies nobody sets is a puzzle, not a courtesy.
 */
import { useConsent } from "@/components/consent/ConsentProvider";

export function CookieChoicesLink({ className = "" }: { className?: string }) {
  const { reopen, ready, trackingEnabled } = useConsent();
  // `ready` gates the render for the same reason the pixels are gated on it: before the
  // cookie is read we do not know whether there is anything to offer.
  if (!ready || !trackingEnabled) return null;

  return (
    <button type="button" onClick={reopen} className={className}>
      Cookie choices
    </button>
  );
}
