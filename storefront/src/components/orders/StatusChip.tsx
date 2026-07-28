/** Order status as a customer-facing pill. The backend stores raw slugs on a plain
 * CharField (no choices constraint), so an unrecognised value is expected, not
 * exceptional: render it verbatim in the neutral tone rather than crash or — worse —
 * hide the row, which would make an order vanish from a customer's history.
 *
 * Only palette tokens from globals.css are used; there is no green/amber scale beyond
 * accent (forest green) and gold, so the three tones map onto those plus beige/muted. */

type Tone = "good" | "waiting" | "neutral";

const TONE_CLASSES: Record<Tone, string> = {
  // Gold-on-cream fails contrast as text, so the waiting tone tints the background and
  // keeps ink text — the same treatment as the ProductCard sale badge.
  good: "bg-accent/10 text-accent-strong",
  waiting: "bg-gold/20 text-foreground",
  neutral: "bg-beige text-muted",
};

/** Pinned labels: the customer never sees a raw slug for a status we know about.
 * Grouping: in-flight-and-fine → good, needs-something-to-happen → waiting,
 * stopped/reversed → neutral. */
const STATUSES: Record<string, { label: string; tone: Tone }> = {
  pending_payment: { label: "Awaiting payment", tone: "waiting" },
  processing: { label: "Processing", tone: "waiting" },
  on_hold: { label: "On hold", tone: "waiting" },
  shipped: { label: "Shipped", tone: "good" },
  delivered: { label: "Delivered", tone: "good" },
  completed: { label: "Completed", tone: "good" },
  cancelled: { label: "Cancelled", tone: "neutral" },
  expired: { label: "Expired", tone: "neutral" },
  refunded: { label: "Refunded", tone: "neutral" },
};

export function StatusChip({ status }: { status: string }) {
  const known = STATUSES[status];
  return (
    <span
      className={
        "inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium " +
        TONE_CLASSES[known?.tone ?? "neutral"]
      }
    >
      {known?.label ?? status}
    </span>
  );
}
