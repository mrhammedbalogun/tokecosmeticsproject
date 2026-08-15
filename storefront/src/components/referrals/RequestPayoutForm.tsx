"use client";

/**
 * Asking for the money.
 *
 * The terms checkbox appears only on a referrer's FIRST payout and is required, because
 * auto-enrolment means nobody ever agreed to anything — the clauses that matter in a
 * dispute (no self-referral, clawback when an order comes back) are exactly the ones
 * somebody would deny having seen. After the first acceptance the backend stops asking
 * and so does this.
 *
 * The amount is stated in the button rather than left to the customer to type. There is
 * nothing to choose: a payout claims the whole available balance in one currency, and a
 * partial-amount field would be a decision the programme does not actually offer.
 *
 * IT RENDERS NO SUCCESS STATE, deliberately. A successful request revalidates the page,
 * which re-renders with an open payout and swaps this component out for the confirmation
 * panel in `payouts/page.tsx` — so a success branch here would be unreachable code that
 * looks like the thing handling the happy path. It handles failure only.
 */
import { useActionState } from "react";
import type { PayoutRequestState } from "@/app/(shop)/account/referrals/actions";
import type { Wallet } from "@/lib/referrals";

const ERROR_ID = "payout-request-error";

export function RequestPayoutForm({
  wallet,
  needsTerms,
  action,
}: {
  wallet: Wallet;
  needsTerms: boolean;
  action: (state: PayoutRequestState, formData: FormData) => Promise<PayoutRequestState>;
}) {
  const [state, formAction, pending] = useActionState(action, {});

  return (
    <form action={formAction} className="space-y-4">
      <input type="hidden" name="currency" value={wallet.currency} />

      <div aria-live="polite">
        {state.error && (
          <p id={ERROR_ID} role="alert" className="text-sm text-red-700">
            {state.error}
          </p>
        )}
      </div>

      {/* `needsTerms` decides whether to render it; `state.code` re-opens it if the
          server disagreed — the two can differ when a request is made in two tabs. */}
      {(needsTerms || state.code === "terms_required") && (
        <label className="flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            name="accept_terms"
            required
            className="mt-0.5 h-4 w-4 rounded border-line text-accent focus:ring-accent/40"
            aria-describedby={state.error ? ERROR_ID : undefined}
          />
          <span className="text-muted">
            I agree to the affiliate programme terms — including that I can&rsquo;t earn on
            my own orders, and that commission on a returned order is reversed or taken
            off a later payout.
          </span>
        </label>
      )}

      <button
        type="submit"
        disabled={pending}
        className="rounded-[var(--radius-card)] bg-accent px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
      >
        {pending ? "Requesting…" : `Request ${wallet.available_display}`}
      </button>
    </form>
  );
}
