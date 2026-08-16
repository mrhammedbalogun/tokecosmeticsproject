import type { Metadata } from "next";
import Link from "next/link";
import {
  approvePayoutAction,
  markPayoutPaidAction,
  rejectPayoutAction,
} from "@/app/(shell)/referrals/actions";
import { PayoutCard } from "@/components/referrals/PayoutCard";
import { Pagination } from "@/components/Pagination";
import { getAdminMeOrNull } from "@/lib/admin-me";
import { ApiError } from "@/lib/api";
import { pageCount } from "@/lib/pagination";
import {
  PAYOUT_STATUSES,
  REFERRAL_PAGE_SIZE,
  STATUS_LABEL,
  isAging,
  parsePayoutFilters,
  payoutsQueryString,
  type PayoutPage,
} from "@/lib/referrals";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Referral payouts" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PATH = "/referrals";
const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none";

/**
 * `/referrals` — the payout queue.
 *
 * The one screen in the admin that shows an unmasked bank account number, because a
 * person cannot make a transfer to `•••• 6789`. Every GET here writes an audit row for
 * that reason (`PayoutQueueViewSet.audit_reads`).
 *
 * ORDERED OLDEST-WAITING FIRST, by the API. A payout queue is a work queue: the row that
 * matters is the one that has been waiting longest, and a newest-first list buries it at
 * exactly the moment it becomes urgent.
 *
 * WHAT IS NOT HERE, deliberately: blocking a referrer and writing a manual adjustment.
 * Those live at `/referrals/referrers`. Different job — this page is "settle what people
 * have asked for", and mixing "punish a referrer" into the same screen invites doing it
 * in the same rushed month-end pass.
 */
export default async function ReferralPayoutsPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  await requireAdmin(PATH);
  const filters = parsePayoutFilters(await searchParams);

  const held = new Set((await getAdminMeOrNull())?.scopes ?? []);
  // Ergonomics, not authorization: the endpoints carry `referrals.manage` / `referrals.pay`
  // themselves. This only decides whether a button is worth showing to someone who would
  // get a 403 for pressing it.
  const canDecide = held.has("referrals.manage");
  const canPay = held.has("referrals.pay");

  let page: PayoutPage | null = null;
  let loadError: string | null = null;
  try {
    page = await fetchWithAuthOrBounce<PayoutPage>(
      `/admin/referral-payouts/${payoutsQueryString(filters)}`,
      PATH,
    );
  } catch (e) {
    loadError =
      e instanceof ApiError && e.status === 403
        ? "Your role cannot see referral payouts."
        : "The payout queue could not be loaded.";
  }

  const rows = page?.results ?? [];
  const waiting = rows.filter((r) => r.status === "requested");
  const late = waiting.filter(isAging);

  return (
    <section className="mx-auto max-w-5xl">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl">Referral payouts</h1>
          <p className="mt-1 text-sm text-muted">
            Commission referrers have asked to be paid. Transfers are made by hand — record
            the bank&rsquo;s reference when the money leaves.
          </p>
        </div>
        {/* Blocking and hand-written corrections live on their own page, off the screen
            that gets worked in a rush at month end. */}
        <Link
          href="/referrals/referrers"
          className="text-sm text-accent-strong underline underline-offset-2"
        >
          Referrers
        </Link>
      </header>

      {late.length > 0 && (
        <p
          role="status"
          className="mb-4 rounded-[var(--radius-card)] border border-warn/50 bg-warn/5 p-3 text-sm text-warn"
        >
          {late.length} request{late.length === 1 ? " has" : "s have"} been waiting more
          than a fortnight. Somebody is owed money and cannot see why it is taking so long.
        </p>
      )}

      <form method="get" className="mb-4 grid gap-3 rounded-[var(--radius-card)] border border-line bg-surface p-4 sm:grid-cols-3">
        <label className="block text-xs text-muted">
          Status
          <select name="status" defaultValue={filters.status} className={`mt-1 ${FIELD}`}>
            <option value="">Any status</option>
            {PAYOUT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-muted">
          Referrer
          <input
            name="search"
            defaultValue={filters.search}
            placeholder="Email, Toke ID or bank reference"
            className={`mt-1 ${FIELD}`}
          />
        </label>
        <div className="flex items-end gap-2">
          <button
            type="submit"
            className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent hover:text-accent"
          >
            Filter
          </button>
          {(filters.status || filters.search) && (
            <Link href={PATH} className="text-sm text-muted underline underline-offset-2">
              Clear
            </Link>
          )}
        </div>
      </form>

      {loadError && (
        <p role="alert" className="rounded-[var(--radius-card)] border border-warn/40 bg-warn/5 p-4 text-sm text-warn">
          {loadError}
        </p>
      )}

      {!loadError && rows.length === 0 && (
        <p className="rounded-[var(--radius-card)] border border-line bg-surface p-6 text-center text-sm text-muted">
          {filters.status || filters.search
            ? "No payouts match that filter."
            : "No payout requests yet. They appear here the moment a referrer asks."}
        </p>
      )}

      <ul className="space-y-3">
        {rows.map((row) => (
          <PayoutCard
            key={row.id}
            row={row}
            canDecide={canDecide}
            canPay={canPay}
            onApprove={approvePayoutAction}
            onReject={rejectPayoutAction}
            onMarkPaid={markPayoutPaidAction}
          />
        ))}
      </ul>

      {page && page.count > 0 && (
        <div className="mt-4">
          <Pagination
            basePath={PATH}
            page={filters.page}
            total={pageCount(page.count, REFERRAL_PAGE_SIZE)}
            // `buildQuery` wants no leading "?" (see Pagination) — the same builder the
            // page filtered with, so page 2 keeps the filters page 1 was showing.
            buildQuery={(target) =>
              payoutsQueryString({ ...filters, page: target }).replace(/^\?/, "")
            }
          />
        </div>
      )}
    </section>
  );
}
