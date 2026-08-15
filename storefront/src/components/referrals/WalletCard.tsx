/**
 * One currency's balance, and the single most important question on the page: can I
 * take this money out yet, and if not, how much further is it?
 *
 * VOCABULARY, decided 2026-08-15: this surface says "payout", never "withdraw" and never
 * "wallet". What the shop owes an affiliate is a trade payable it settles by bank
 * transfer — an ordinary supplier payment — and words that suggest the shop is holding
 * customer funds describe something it never does. See the runbook's "Questions for a
 * Nigerian fintech lawyer" for the reasoning. (The `Wallet` TYPE name is internal and
 * stays; no customer reads a type.)
 *
 * A server component — nothing here is interactive except the payout link, which is a
 * plain anchor to the payouts page. The page never invents a cross-currency total: the
 * programme does not convert, so one card per currency is the honest shape.
 */
import Link from "next/link";
import type { Wallet } from "@/lib/referrals";

export function WalletCard({ wallet }: { wallet: Wallet }) {
  const pct = progressPercent(wallet);

  return (
    <section className="rounded-[var(--radius-card)] border border-line bg-surface p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.16em] text-muted">
            Available for payout
          </p>
          <p className="mt-1 font-display text-4xl leading-none text-accent-strong">
            {wallet.available_display}
          </p>
          <p className="mt-2 text-sm text-muted">
            {wallet.pending_display} still in its holding period
          </p>
        </div>

        <PayoutControl wallet={wallet} />
      </div>

      {/* The progress bar only earns its place while the customer is still short. Once
          they can request a payout it says nothing the button above has not already said. */}
      {!wallet.can_request && wallet.open_request_id === null && (
        <div className="mt-6">
          <div
            className="h-2 w-full overflow-hidden rounded-full bg-beige"
            role="progressbar"
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`Progress towards the ${wallet.threshold_display} minimum payout`}
          >
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="mt-2 text-sm text-muted">
            {isNegative(wallet.available) ? (
              <>
                A returned order was refunded after you were paid, so this balance is
                behind by {stripSign(wallet.available_display)}. Your next earnings clear
                it first.
              </>
            ) : (
              <>
                <strong className="font-medium text-foreground">
                  {wallet.remaining_to_threshold_display}
                </strong>{" "}
                to go before you can request a payout. Your balance rolls over until then.
              </>
            )}
          </p>
        </div>
      )}

      <dl className="mt-6 grid grid-cols-2 gap-4 border-t border-line pt-4 text-sm sm:grid-cols-3">
        <Stat label="Earned all time" value={wallet.lifetime_display} />
        <Stat label="Paid out" value={wallet.paid_display} />
        <Stat label="Minimum payout" value={wallet.threshold_display} />
      </dl>
    </section>
  );
}

function PayoutControl({ wallet }: { wallet: Wallet }) {
  if (wallet.open_request_id !== null) {
    return (
      <div className="rounded-[var(--radius-card)] bg-beige px-4 py-3 text-sm">
        <p className="font-medium">Payout in progress</p>
        <Link href="/account/referrals/payouts" className="text-accent-strong underline underline-offset-2">
          Track it
        </Link>
      </div>
    );
  }
  if (!wallet.can_request) {
    return (
      <span
        className="cursor-not-allowed rounded-[var(--radius-card)] border border-line px-5 py-2.5 text-sm text-muted"
        aria-disabled="true"
      >
        Request a payout
      </span>
    );
  }
  return (
    <Link
      href={`/account/referrals/payouts?currency=${wallet.currency}`}
      className="rounded-[var(--radius-card)] bg-accent px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-strong"
    >
      Request a payout of {wallet.available_display}
    </Link>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted">{label}</dt>
      <dd className="mt-0.5 font-medium">{value}</dd>
    </div>
  );
}

/**
 * Computed from the raw decimal strings, not the display ones — those carry a currency
 * symbol and thousands separators, and `parseFloat("₦48,500.00")` is NaN.
 *
 * Float arithmetic is fine HERE and nowhere else on this page: the result is a bar
 * width, so a rounding error of 10^-9 is invisible. Every number a customer READS comes
 * from the backend already formatted.
 */
function progressPercent(wallet: Wallet): number {
  const available = Number(wallet.available);
  const threshold = Number(wallet.threshold);
  if (!Number.isFinite(available) || !Number.isFinite(threshold) || threshold <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((available / threshold) * 100)));
}

function isNegative(raw: string): boolean {
  return Number(raw) < 0;
}

/** "−₦1,000.00" → "₦1,000.00", for a sentence that already says "behind by". */
function stripSign(display: string): string {
  return display.replace(/^-/, "");
}
