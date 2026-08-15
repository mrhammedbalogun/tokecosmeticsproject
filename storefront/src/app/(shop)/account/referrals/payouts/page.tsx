import type { Metadata } from "next";
import Link from "next/link";
import {
  formatReferralDate,
  getPayoutMethods,
  getPayouts,
  getReferralOverview,
  type Payout,
  type Wallet,
} from "@/lib/referrals";
import { first } from "@/lib/search-params";
import { PayoutMethodForm } from "@/components/referrals/PayoutMethodForm";
import { RequestPayoutForm } from "@/components/referrals/RequestPayoutForm";
import { requestPayoutAction, savePayoutMethodAction } from "../actions";

export const metadata: Metadata = { title: "Referral payouts" };

const PATH = "/account/referrals/payouts";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/**
 * Bank details, the request-a-payout button, and the history of what has been sent.
 *
 * VOCABULARY: "payout", never "withdraw" — see WalletCard.tsx for why the distinction
 * between an ordinary trade payable and a customer-funds balance is worth the words.
 *
 * Split off the dashboard rather than folded into it because the two are different
 * visits: the dashboard is "give me my link", this is "pay me". Keeping the bank form on
 * its own page also keeps a form that emails the account holder on every save away from
 * the page people open casually.
 *
 * The `?currency=` parameter comes from the payout button on the dashboard, so the right
 * wallet is already selected. It is untrusted URL input and is only ever used to CHOOSE
 * among the wallets the API returned — never forwarded anywhere.
 */
export default async function ReferralPayoutsPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const requested = (first((await searchParams).currency) ?? "").toUpperCase();
  const [overview, methods, payouts] = await Promise.all([
    getReferralOverview(PATH),
    getPayoutMethods(PATH),
    getPayouts(PATH),
  ]);

  const wallets = overview.wallets;
  const selected =
    wallets.find((w) => w.currency === requested) ?? wallets.find((w) => w.can_request) ?? wallets[0];
  const needsTerms = overview.terms_accepted_at === null;

  return (
    <div className="space-y-8">
      <div>
        <h2 className="font-display text-2xl">Payouts</h2>
        <p className="mt-1 text-sm text-muted">
          Request what you&rsquo;ve earned, and manage where it&rsquo;s sent.{" "}
          <Link
            href="/account/referrals"
            className="text-accent-strong underline underline-offset-2"
          >
            Back to your link
          </Link>
        </p>
      </div>

      {wallets.length === 0 ? (
        <p className="rounded-[var(--radius-card)] border border-dashed border-line p-8 text-center text-sm text-muted">
          You haven&rsquo;t earned anything yet, so there&rsquo;s nothing to be paid out.
          Add your bank details whenever you like — they&rsquo;ll be ready when you need
          them.
        </p>
      ) : (
        <section className="rounded-[var(--radius-card)] border border-line bg-surface p-6">
          <h3 className="font-display text-xl">Request a payout</h3>
          <div className="mt-4">
            {selected && <PayoutRequestSection
              wallet={selected}
              hasMethod={methods.some((m) => m.currency === selected.currency)}
              needsTerms={needsTerms}
              openPayout={payouts.results.find((p) => p.id === selected.open_request_id) ?? null}
            />}
          </div>

          {wallets.length > 1 && (
            <p className="mt-4 border-t border-line pt-4 text-sm text-muted">
              Other balances:{" "}
              {wallets
                .filter((w) => w.currency !== selected?.currency)
                .map((w, i) => (
                  <span key={w.currency}>
                    {i > 0 && " · "}
                    <Link
                      href={`${PATH}?currency=${w.currency}`}
                      className="text-accent-strong underline underline-offset-2"
                    >
                      {w.available_display}
                    </Link>
                  </span>
                ))}
            </p>
          )}
        </section>
      )}

      <section className="rounded-[var(--radius-card)] border border-line bg-surface p-6">
        <h3 className="font-display text-xl">Bank details</h3>
        <p className="mt-1 text-sm text-muted">
          Where we send your payouts. We never show your full account number back to you.
        </p>
        <div className="mt-5">
          <PayoutMethodForm
            currencies={payoutCurrencies(wallets, methods.map((m) => m.currency))}
            existing={methods}
            action={savePayoutMethodAction}
            defaultCurrency={selected?.currency ?? methods[0]?.currency ?? "NGN"}
          />
        </div>
      </section>

      <section>
        <h3 className="font-display text-xl">Payout history</h3>
        <div className="mt-4">
          {payouts.results.length === 0 ? (
            <p className="rounded-[var(--radius-card)] border border-dashed border-line p-8 text-center text-sm text-muted">
              No payouts yet.
            </p>
          ) : (
            <ul className="space-y-3">
              {payouts.results.map((payout) => (
                <PayoutRow key={payout.id} payout={payout} />
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}

function PayoutRequestSection({
  wallet,
  hasMethod,
  needsTerms,
  openPayout,
}: {
  wallet: Wallet;
  hasMethod: boolean;
  needsTerms: boolean;
  openPayout: Payout | null;
}) {
  /**
   * THE CONFIRMATION LIVES HERE, not in the form's own success state, and that was a
   * correction rather than a preference. Requesting a payout revalidates this page, so
   * the branch below replaces `RequestPayoutForm` outright — the banner the form
   * rendered on success unmounted before anyone could read it (caught by clicking the
   * button in a browser; the form's own tests were perfectly happy).
   *
   * Driving it from the fetched payout instead means the same panel greets a customer
   * who requested five minutes ago and one who comes back tomorrow, which is what the
   * customer actually needs: how much, and when it lands.
   */
  if (openPayout) {
    return (
      <div
        role="status"
        className="rounded-[var(--radius-card)] border border-accent/30 bg-accent/5 p-5"
      >
        <p className="font-display text-xl text-accent-strong">
          Payout requested — {openPayout.amount_display}
        </p>
        <p className="mt-2 text-sm text-muted">
          {openPayout.status === "approved"
            ? "Approved — the transfer is on its way to "
            : "We're reviewing it. Payouts are sent by bank transfer on the last working day of the month, to "}
          {openPayout.bank_name} {openPayout.account_masked}. You&rsquo;ll get an email
          with the transfer reference once it goes.
        </p>
      </div>
    );
  }
  if (wallet.open_request_id !== null) {
    // A request exists but is not on this page of the history (a long history, page 2).
    // Rare, and it must still not offer a second payout request.
    return (
      <p className="text-sm text-muted">
        Your {wallet.currency} payout is being processed — see the history below.
      </p>
    );
  }
  if (!hasMethod) {
    return (
      <p className="text-sm text-muted">
        Add the bank account you want your {wallet.currency} payouts sent to, below, and
        the payout button will appear here.
      </p>
    );
  }
  if (!wallet.can_request) {
    return (
      <p className="text-sm text-muted">
        You have <strong className="font-medium text-foreground">{wallet.available_display}</strong>{" "}
        available. The minimum payout is {wallet.threshold_display} —{" "}
        {wallet.remaining_to_threshold_display} to go. Your balance rolls over until then.
      </p>
    );
  }
  return <RequestPayoutForm wallet={wallet} needsTerms={needsTerms} action={requestPayoutAction} />;
}

function PayoutRow({ payout }: { payout: Payout }) {
  return (
    <li className="rounded-[var(--radius-card)] border border-line bg-surface p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="font-display text-lg">{payout.amount_display}</p>
        <StatusChip status={payout.status} label={payout.status_label} />
      </div>
      <p className="mt-1 text-sm text-muted">
        Requested {formatReferralDate(payout.created_at)}
        {payout.paid_at && ` · sent ${formatReferralDate(payout.paid_at)}`}
        {payout.bank_name && ` · ${payout.bank_name} ${payout.account_masked}`}
      </p>
      {payout.reference && (
        <p className="mt-1 text-sm text-muted">
          Bank reference <span className="font-mono">{payout.reference}</span>
        </p>
      )}
      {/* Staff write this when they refuse a request. It is the only explanation the
          customer gets, so it is shown prominently rather than tucked into small print. */}
      {payout.customer_message && (
        <p className="mt-2 rounded-[var(--radius-card)] bg-beige p-3 text-sm">
          {payout.customer_message}
        </p>
      )}
    </li>
  );
}

const CHIP: Record<string, string> = {
  requested: "bg-beige text-muted",
  approved: "bg-accent/10 text-accent-strong",
  paid: "bg-accent/10 text-accent-strong",
  rejected: "bg-red-50 text-red-700",
};

function StatusChip({ status, label }: { status: string; label: string }) {
  return (
    <span
      className={
        "rounded-full px-2.5 py-1 text-xs font-medium " + (CHIP[status] ?? "bg-beige text-muted")
      }
    >
      {label}
    </span>
  );
}

/**
 * Which currencies the bank form may be filled in for.
 *
 * The referrer's own wallets, plus any currency they have ALREADY saved an account for —
 * without that second half, a referrer whose GBP balance was fully paid out would find
 * their saved GBP account uneditable, because the wallet it belonged to has gone.
 */
function payoutCurrencies(wallets: Wallet[], saved: string[]) {
  const codes = [...new Set([...wallets.map((w) => w.currency), ...saved])];
  return codes.map((code) => ({ code, label: code }));
}
