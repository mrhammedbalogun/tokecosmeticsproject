"use client";

/**
 * Business Decisions (2026-08-27): the two referral percentages, on one form.
 *
 * ── WHY ONE SAVE AND NOT A SWITCH PER FIELD ────────────────────────────────────────
 *
 * The tax screen next door flips its master switch on click, because a switch that needs
 * a second click gets left half-flipped. These are the opposite case: both values are
 * TYPED, and saving keystrokes as they happen would write 2% on the way to 20%. They also
 * belong together — the referrer's cut and the buyer's discount are one offer, and the
 * question an Owner is actually asking is "what does this programme cost us", which is the
 * two numbers added up. So: one form, one Save, and a live worked example above it.
 *
 * The example is the whole point of the screen. "10% and 5%" is abstract; "on a ₦100,000
 * order the customer pays ₦95,000, the referrer earns ₦9,500, and the shop keeps
 * ₦85,500" is the sentence somebody can actually make a decision from — and it is the
 * sentence that makes the commission-after-discount rule visible rather than a surprise
 * discovered later in a payout query.
 */
import { startTransition, useState } from "react";
import { saveBusinessDecisionsAction } from "@/app/(shell)/business-decisions/actions";
import type { BusinessDecisionsRow } from "@/lib/business-decisions";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

/** The example order the worked figures are based on. A round number in the shop's home
 * currency, so the arithmetic is checkable in the reader's head. */
const EXAMPLE = 100000;

const naira = (amount: number) =>
  `₦${amount.toLocaleString("en-NG", { maximumFractionDigits: 2 })}`;

function Worked({ commission, discount }: { commission: string; discount: string }) {
  const commissionRate = Number(commission);
  const discountRate = Number(discount);
  if (!Number.isFinite(commissionRate) || !Number.isFinite(discountRate)) return null;

  const customerPays = EXAMPLE - (EXAMPLE * discountRate) / 100;
  // Commission is worked out on what the customer actually paid, not the list price —
  // the same rule the backend applies in referrals.services.commission_base. Showing it
  // here is what stops "why is my commission ₦9,500 and not ₦10,000" being a support
  // ticket.
  const referrerEarns = (customerPays * commissionRate) / 100;

  return (
    <dl className="mt-4 grid gap-2 rounded-[var(--radius-card)] border border-line bg-shell/5 p-4 text-sm">
      <div className="flex justify-between gap-4">
        <dt className="text-muted">A referred order of</dt>
        <dd className="tabular-nums">{naira(EXAMPLE)}</dd>
      </div>
      <div className="flex justify-between gap-4">
        <dt className="text-muted">The customer pays</dt>
        <dd className="tabular-nums">{naira(customerPays)}</dd>
      </div>
      <div className="flex justify-between gap-4">
        <dt className="text-muted">The referrer earns</dt>
        <dd className="tabular-nums">{naira(referrerEarns)}</dd>
      </div>
      <div className="flex justify-between gap-4 border-t border-line pt-2 font-medium">
        <dt>The shop keeps</dt>
        <dd className="tabular-nums">{naira(customerPays - referrerEarns)}</dd>
      </div>
    </dl>
  );
}

export function BusinessDecisions({ decisions }: { decisions: BusinessDecisionsRow }) {
  const [commission, setCommission] = useState(decisions.referrer_commission_percent);
  const [discount, setDiscount] = useState(decisions.customer_discount_percent);
  const [firstOrderOnly, setFirstOrderOnly] = useState(
    decisions.customer_discount_first_order_only,
  );
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setPending(true);
    setSaved(false);
    setErrors({});
    setMessage(null);
    startTransition(async () => {
      const state = await saveBusinessDecisionsAction({
        referrer_commission_percent: commission,
        customer_discount_percent: discount,
        customer_discount_first_order_only: firstOrderOnly,
      });
      setPending(false);
      if (state.savedAt) setSaved(true);
      setErrors(state.fieldErrors ?? {});
      setMessage(state.message ?? null);
    });
  };

  return (
    <form onSubmit={submit} className="max-w-2xl">
      <section className="rounded-[var(--radius-card)] border border-line p-4">
        <h2 className="text-sm font-semibold">Referral programme</h2>
        <p className="mt-1 text-xs text-muted">
          What a referrer earns, and what the person who used their link saves.
        </p>

        {message && (
          <p
            className="mt-3 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn"
            role="alert"
          >
            {message}
          </p>
        )}
        {saved && !message && (
          <p
            className="mt-3 rounded border border-ok/30 bg-ok/10 p-2 text-sm text-ok"
            role="status"
          >
            Saved.
          </p>
        )}

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="block text-xs text-muted">
            Referrer commission (%)
            <input
              type="number"
              min="0"
              max="100"
              step="0.01"
              value={commission}
              onChange={(e) => setCommission(e.target.value)}
              className={`mt-1 ${FIELD}`}
            />
            <span className="mt-1 block text-[11px]">
              Paid on what the customer actually pays for the products — after the discount
              below, and never on delivery or tax.
            </span>
            {errors.referrer_commission_percent && (
              <span className="mt-1 block text-[11px] text-warn" role="alert">
                {errors.referrer_commission_percent}
              </span>
            )}
          </label>

          <label className="block text-xs text-muted">
            Customer discount (%)
            <input
              type="number"
              min="0"
              max="100"
              step="0.01"
              value={discount}
              onChange={(e) => setDiscount(e.target.value)}
              className={`mt-1 ${FIELD}`}
            />
            <span className="mt-1 block text-[11px]">
              Taken off the products at checkout, straight away. Set either number to 0 to
              switch that half of the programme off.
            </span>
            {errors.customer_discount_percent && (
              <span className="mt-1 block text-[11px] text-warn" role="alert">
                {errors.customer_discount_percent}
              </span>
            )}
          </label>
        </div>

        <label className="mt-4 flex items-start gap-2 text-xs text-muted">
          <input
            type="checkbox"
            checked={firstOrderOnly}
            onChange={(e) => setFirstOrderOnly(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-line"
          />
          <span>
            Only give the discount on a customer’s first order.
            <span className="mt-1 block text-[11px]">
              Off means every order placed through a referral link gets it, for as long as
              the link is tracking — which is the same rule the commission follows. Turn it
              on if repeat customers start using a friend’s link to keep the discount
              indefinitely.
            </span>
          </span>
        </label>

        <Worked commission={commission} discount={discount} />

        <button
          type="submit"
          disabled={pending}
          className="mt-4 rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          {pending ? "Saving…" : "Save"}
        </button>
      </section>

      {/* These two numbers are printed on a public page and in the affiliate agreement.
          The code moves with them; the prose does not, and nothing here can change it. */}
      <p className="mt-4 rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-xs text-warn">
        Both numbers are advertised on the public Affiliates page and written into the
        affiliate terms. Saving here changes what the shop pays and what the storefront
        says <strong>immediately</strong> — but it does not rewrite the terms page. If you
        change either one, update that wording too.
      </p>
    </form>
  );
}
