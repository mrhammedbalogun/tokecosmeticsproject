import type { Metadata } from "next";
import Link from "next/link";
import { getCommissions, getReferralOverview } from "@/lib/referrals";
import { ActivityList } from "@/components/referrals/ActivityList";
import { EliteTierCard } from "@/components/referrals/EliteTierCard";
import { HowItWorks } from "@/components/referrals/HowItWorks";
import { ShareCard } from "@/components/referrals/ShareCard";
import { WalletCard } from "@/components/referrals/WalletCard";

// The account layout already sets robots noindex for everything beneath it.
export const metadata: Metadata = { title: "Refer a friend" };

const PATH = "/account/referrals";

/**
 * The referral dashboard.
 *
 * Its own overview fetch IS the gate (the account layout's fetch does not re-run on soft
 * navigation) — same pattern as every other page under /account.
 *
 * Two fetches, not one: the overview is small and always needed, the activity feed is
 * paginated and independent. They are issued together rather than awaited in sequence so
 * a slow feed does not delay the balance.
 *
 * ORDER OF THE PAGE, because it is a decision rather than a default. Share card first —
 * the overwhelmingly common visit is "give me my link", and making that person scroll
 * past their own balance to reach it would be optimising for the wrong trip. Money
 * second. Explanation last, where somebody who is confused will go looking for it and
 * where it does not sit between a returning referrer and their link.
 */
export default async function ReferralsPage() {
  const [overview, activity] = await Promise.all([
    getReferralOverview(PATH),
    getCommissions(1, PATH),
  ]);

  const recent = activity.results.slice(0, 5);

  return (
    <div className="space-y-8">
      <div>
        <h2 className="font-display text-2xl">Refer a friend</h2>
        <p className="mt-1 text-sm text-muted">
          {overview.referred_customers > 0 ? (
            <>
              {overview.referred_customers}{" "}
              {overview.referred_customers === 1 ? "person has" : "people have"} shopped
              with your link so far.
            </>
          ) : (
            <>Share Toke Cosmetics with people you know and earn on what they buy.</>
          )}
        </p>
      </div>

      {overview.is_blocked && (
        <p
          role="alert"
          className="rounded-[var(--radius-card)] border border-red-200 bg-red-50 p-4 text-sm text-red-800"
        >
          Your referral account is on hold, so new orders won&rsquo;t earn commission and
          payouts are paused. Please contact us and we&rsquo;ll sort it out.
        </p>
      )}

      <ShareCard
        code={overview.code}
        shareUrl={overview.share_url}
        commissionPercent={trimPercent(overview.commission_percent)}
      />

      {overview.wallets.length > 0 ? (
        <div className="space-y-4">
          {overview.wallets.map((wallet) => (
            <WalletCard key={wallet.currency} wallet={wallet} />
          ))}
        </div>
      ) : (
        <section className="rounded-[var(--radius-card)] border border-dashed border-line p-8 text-center">
          <p className="font-display text-xl">Nothing earned yet</p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-muted">
            Your earnings will appear here as soon as someone orders through your link.
          </p>
        </section>
      )}

      {overview.tiers.map((tier) => (
        <EliteTierCard key={tier.currency} tier={tier} />
      ))}

      <section>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="font-display text-2xl">Recent activity</h2>
          {activity.count > recent.length && (
            <Link
              href="/account/referrals/activity"
              className="text-sm text-accent-strong underline underline-offset-2"
            >
              See all {activity.count}
            </Link>
          )}
        </div>
        <div className="mt-4">
          <ActivityList
            commissions={recent}
            // Adjustments are shown in full on the dedicated activity page. Here only the
            // unsettled ones matter — a settled clawback is history, and history that
            // reduces a balance the card above already shows correctly reads as a second
            // deduction.
            adjustments={activity.adjustments.filter((a) => !a.settled)}
            holdDays={overview.hold_days}
          />
        </div>
      </section>

      <HowItWorks
        commissionPercent={trimPercent(overview.commission_percent)}
        cookieDays={overview.cookie_days}
        holdDays={overview.hold_days}
      />

      <p className="text-sm text-muted">
        Payouts and bank details live on the{" "}
        <Link
          href="/account/referrals/payouts"
          className="text-accent-strong underline underline-offset-2"
        >
          payouts page
        </Link>
        .
      </p>
    </div>
  );
}

/** "10.00" → "10". The API sends a Decimal string because it is money-adjacent; a
 * headline that reads "Earn 10.00% every time" reads like a spreadsheet. Kept exact for
 * a genuine fraction ("12.50" stays "12.50"). */
function trimPercent(raw: string): string {
  return raw.replace(/\.0+$/, "");
}
