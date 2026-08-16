/**
 * The fine print, drawn as what it actually is: a sequence in time.
 *
 * ── WHY A TIMELINE AND NOT "01 / 02 / 03" ───────────────────────────────────────────
 *
 * The reference design numbers its sections 01–04 — ordinals over things that are not a
 * sequence, which is decoration wearing the costume of structure. What IS a sequence
 * here is a single sale: somebody clicks, somebody buys, the parcel ships, the money is
 * held, the money is paid. The numbers on this rail are DAYS, and days are the thing a
 * referrer actually needs to know.
 *
 * That is also the question support gets asked. Not "what is the rate" — the offer row
 * above answers that — but "why isn't my money here yet". So the holding period is not
 * buried in a disclosure; it is a station on the line, in the same type as everything
 * else.
 *
 * DELIBERATELY SAYS NOTHING ABOUT THE RATE. `OfferRow` states it once. Two places
 * quoting a percentage is two places to forget when it changes, even with both fed from
 * the same fetch.
 */
export function SaleTimeline({
  cookieDays,
  holdDays,
}: {
  cookieDays: number;
  holdDays: number;
}) {
  const steps = [
    {
      marker: "Day 0",
      title: "Someone opens your link",
      body: "They're tracked to you from that moment. If they open a different link afterwards, the newest one takes the credit — so it pays to stay in front of people.",
    },
    {
      marker: `${cookieDays} days`,
      title: "They shop, at the usual price",
      body: "That's how long you stay credited for. Nothing changes for them — no code to enter at checkout, no discount to claim, same price they'd have paid anyway.",
    },
    {
      marker: `${holdDays} days`,
      title: "It ships, then your share waits",
      body: `Commission is held for ${holdDays} days after dispatch so the return window can close. If the order comes back, the commission comes back with it.`,
    },
    {
      marker: "Any time",
      title: "You ask to be paid",
      body: "Once a balance clears the minimum for that currency, request a payout and it goes to your bank. Below the minimum it simply rolls over — nothing expires.",
    },
  ];

  return (
    <section aria-labelledby="timeline-heading" className="wrap py-20 sm:py-28">
      <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">
        The life of one sale
      </p>
      <h2
        id="timeline-heading"
        className="mt-4 text-2xl uppercase tracking-[0.14em] sm:text-[1.75rem]"
      >
        Where your money is
      </h2>

      {/* The rail: a left border with dots on mobile, a top border with dots from md up.
          One list, two orientations — a second markup tree would be a second thing to
          keep in sync. */}
      <ol className="mt-14 grid gap-10 border-l border-line pl-7 md:grid-cols-4 md:gap-8 md:border-l-0 md:border-t md:pl-0">
        {steps.map((step) => (
          <li key={step.marker} className="relative md:pr-8 md:pt-10">
            <span
              aria-hidden
              className="absolute -left-[1.9375rem] top-2 h-2 w-2 rounded-full bg-accent md:-top-1 md:left-0"
            />
            <p className="font-display text-3xl text-accent-strong">{step.marker}</p>
            <h3 className="mt-4 text-[11px] font-medium uppercase tracking-[0.16em]">
              {step.title}
            </h3>
            <p className="mt-3 text-sm leading-relaxed text-muted">{step.body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
