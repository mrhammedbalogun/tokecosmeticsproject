/**
 * The programme terms, in the customer's words rather than the contract's.
 *
 * EVERY NUMBER HERE IS A PROP, sourced from the API, which sources it from Django
 * settings — the same settings the commission is actually calculated from. Hardcoding
 * "10%" or "30 days" in this file would be writing a promise in a place that cannot
 * change when the promise does, and the gap between advertised and paid is the kind of
 * bug a customer finds first.
 *
 * The rules a referrer is most likely to be surprised by are stated plainly rather than
 * buried: commission excludes delivery and tax, self-referral is not allowed, and the
 * money is held for 60 days after dispatch. Somebody who reads this page should never
 * have to email support to find out why their balance is not what they expected.
 */
const STEPS = [
  {
    title: "Share your link",
    body: "Post it, message it, put it in your bio. Anyone who opens it is yours for the tracking window — even if they come back days later.",
  },
  {
    title: "They shop as normal",
    body: "Nothing changes for them. They don't need a code at checkout and they pay the same price.",
  },
  {
    title: "You earn on what they spend",
    body: "Commission is worked out on the products only — delivery and tax are not included.",
  },
  {
    title: "Withdraw to your bank",
    body: "Once your balance clears the minimum, request a payout and we'll send it by bank transfer.",
  },
] as const;

export function HowItWorks({
  commissionPercent,
  cookieDays,
  holdDays,
}: {
  commissionPercent: string;
  cookieDays: number;
  holdDays: number;
}) {
  return (
    <section className="rounded-[var(--radius-card)] border border-line bg-surface p-6 sm:p-8">
      <h2 className="font-display text-2xl">How it works</h2>

      <ol className="mt-6 grid gap-6 sm:grid-cols-2">
        {STEPS.map((step, i) => (
          <li key={step.title} className="flex gap-4">
            <span
              aria-hidden
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/10 font-display text-sm text-accent-strong"
            >
              {i + 1}
            </span>
            <div>
              <h3 className="font-medium">{step.title}</h3>
              <p className="mt-1 text-sm text-muted">{step.body}</p>
            </div>
          </li>
        ))}
      </ol>

      <dl className="mt-8 grid gap-4 border-t border-line pt-6 sm:grid-cols-3">
        <Fact term={`${commissionPercent}%`} detail="of every qualifying sale" />
        <Fact term={`${cookieDays} days`} detail="tracking window from their first click" />
        <Fact term={`${holdDays} days`} detail="held after dispatch, in case of returns" />
      </dl>

      <details className="mt-6 border-t border-line pt-6">
        <summary className="cursor-pointer text-sm font-medium">
          The details worth knowing
        </summary>
        <ul className="mt-3 space-y-2 text-sm text-muted">
          <li>
            Commission is calculated on net sales — the products, after any discount.
            Delivery charges and tax are excluded.
          </li>
          <li>
            An order has to be paid for and dispatched before it counts, and your
            commission is held for {holdDays} days after dispatch so the return window can
            close.
          </li>
          <li>
            If a customer returns an order, the commission on it is reversed. If you had
            already been paid for it, the amount is taken off your next payout.
          </li>
          <li>
            You can&rsquo;t use your own link. Orders you place yourself — or from another
            account with your email or phone number — don&rsquo;t earn commission.
          </li>
          <li>
            Balances roll over until they reach the minimum, and each currency is paid out
            separately. Payouts are reviewed and sent monthly by bank transfer.
          </li>
          <li>
            Please say when you&rsquo;re sharing a paid link — a simple #ad or #partner is
            all it takes, and it&rsquo;s what the advertising rules ask for.
          </li>
        </ul>
      </details>
    </section>
  );
}

function Fact({ term, detail }: { term: string; detail: string }) {
  return (
    <div>
      <dt className="font-display text-3xl text-accent-strong">{term}</dt>
      <dd className="mt-1 text-sm text-muted">{detail}</dd>
    </div>
  );
}
