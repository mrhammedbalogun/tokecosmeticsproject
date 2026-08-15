import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError } from "@/lib/api";
import { first } from "@/lib/search-params";
import { getCommissions, getReferralOverview, type CommissionPage } from "@/lib/referrals";
import { ActivityList } from "@/components/referrals/ActivityList";
import { Pagination } from "@/components/ui/Pagination";

export const metadata: Metadata = { title: "Referral activity" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/** Untrusted URL input → a page number DRF will accept. Same rule as the orders list:
 * anything that is not a positive safe integer falls back to page 1 rather than being
 * forwarded verbatim. */
function parsePage(raw: string | string[] | undefined): number {
  const page = Number(first(raw));
  return Number.isSafeInteger(page) && page > 0 ? page : 1;
}

async function load(page: number, currentPath: string): Promise<CommissionPage> {
  try {
    return await getCommissions(page, currentPath);
  } catch (e) {
    // DRF 404s a page past the last one ("Invalid page") — a bad URL, not an error.
    if (e instanceof ApiError && e.status === 404) notFound();
    // Everything else, including the NEXT_REDIRECT thrown to renew a stale session,
    // must propagate untouched.
    throw e;
  }
}

export default async function ReferralActivityPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const page = parsePage((await searchParams).page);
  // The bounce target must be this exact URL, page included, or renewing mid-history
  // dumps the customer back on page 1.
  const currentPath =
    page === 1 ? "/account/referrals/activity" : `/account/referrals/activity?page=${page}`;

  const [overview, activity] = await Promise.all([
    getReferralOverview(currentPath),
    load(page, currentPath),
  ]);

  return (
    <div>
      <h2 className="font-display text-2xl">Referral activity</h2>
      <p className="mt-1 text-sm text-muted">
        Every order placed with your link.{" "}
        <Link href="/account/referrals" className="text-accent-strong underline underline-offset-2">
          Back to your link
        </Link>
      </p>

      <div className="mt-6">
        <ActivityList
          commissions={activity.results}
          adjustments={activity.adjustments}
          holdDays={overview.hold_days}
        />
      </div>

      <Pagination
        page={page}
        prevHref={activity.previous === null ? null : `/account/referrals/activity?page=${page - 1}`}
        nextHref={activity.next === null ? null : `/account/referrals/activity?page=${page + 1}`}
      />
    </div>
  );
}
