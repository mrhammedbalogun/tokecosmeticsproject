import type { Metadata } from "next";
import Link from "next/link";
import {
  addAdjustmentAction,
  setReferrerBlockedAction,
} from "@/app/(shell)/referrals/referrers/actions";
import { ReferrerActions } from "@/components/referrals/ReferrerActions";
import { Pagination } from "@/components/Pagination";
import { getAdminMeOrNull } from "@/lib/admin-me";
import { ApiError } from "@/lib/api";
import { pageCount } from "@/lib/pagination";
import {
  REFERRAL_PAGE_SIZE,
  parseReferrerFilters,
  referrersQueryString,
  type ReferrerPage,
  type ReferrerRow,
} from "@/lib/referrals";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Referrers" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PATH = "/referrals/referrers";
const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none";

/**
 * `/referrals/referrers` — the abuse and correction surface.
 *
 * A SEPARATE PAGE FROM THE PAYOUT QUEUE, deliberately. The queue answers "settle what
 * people have asked for" and is worked in a rush at month end; this answers "something
 * is wrong with this person's account". Putting the block button on the queue would mean
 * the most consequential action in the programme lives on the screen somebody is
 * clicking through fastest.
 *
 * Blocked referrers sort first — if you opened this page without searching, it is
 * usually to see who is currently stopped and why.
 */
export default async function ReferrersPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  await requireAdmin(PATH);
  const filters = parseReferrerFilters(await searchParams);

  const held = new Set((await getAdminMeOrNull())?.scopes ?? []);
  // Ergonomics only — both endpoints carry `referrals.manage` themselves.
  const canManage = held.has("referrals.manage");

  let page: ReferrerPage | null = null;
  let loadError: string | null = null;
  try {
    page = await fetchWithAuthOrBounce<ReferrerPage>(
      `/admin/referrers/${referrersQueryString(filters)}`,
      PATH,
    );
  } catch (e) {
    loadError =
      e instanceof ApiError && e.status === 403
        ? "Your role cannot see referrers."
        : "The referrer list could not be loaded.";
  }

  const rows = page?.results ?? [];

  return (
    <section className="mx-auto max-w-5xl">
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl">Referrers</h1>
          <p className="mt-1 text-sm text-muted">
            Everyone earning commission. Block someone who is abusing the programme, or
            correct a balance by hand.
          </p>
        </div>
        <Link
          href="/referrals"
          className="text-sm text-accent-strong underline underline-offset-2"
        >
          Payout queue
        </Link>
      </header>

      <form
        method="get"
        className="mb-4 grid gap-3 rounded-[var(--radius-card)] border border-line bg-surface p-4 sm:grid-cols-3"
      >
        <label className="block text-xs text-muted sm:col-span-2">
          Search
          <input
            name="search"
            defaultValue={filters.search}
            placeholder="Name, email, Toke ID or referral code"
            className={`mt-1 ${FIELD}`}
          />
        </label>
        <div className="flex items-end gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              name="blocked"
              value="true"
              defaultChecked={filters.blocked === "true"}
            />
            Blocked only
          </label>
          <button
            type="submit"
            className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent hover:text-accent"
          >
            Filter
          </button>
        </div>
      </form>

      {loadError && (
        <p role="alert" className="rounded-[var(--radius-card)] border border-warn/40 bg-warn/5 p-4 text-sm text-warn">
          {loadError}
        </p>
      )}

      {!loadError && rows.length === 0 && (
        <p className="rounded-[var(--radius-card)] border border-line bg-surface p-6 text-center text-sm text-muted">
          {filters.search || filters.blocked
            ? "Nobody matches that filter."
            : "No referrers yet."}
        </p>
      )}

      <ul className="space-y-3">
        {rows.map((row) => (
          <ReferrerCard
            key={row.id}
            row={row}
            canManage={canManage}
          />
        ))}
      </ul>

      {page && page.count > 0 && (
        <div className="mt-4">
          <Pagination
            basePath={PATH}
            page={filters.page}
            total={pageCount(page.count, REFERRAL_PAGE_SIZE)}
            buildQuery={(target) =>
              referrersQueryString({ ...filters, page: target }).replace(/^\?/, "")
            }
            label="Referrer pages"
          />
        </div>
      )}
    </section>
  );
}

function ReferrerCard({ row, canManage }: { row: ReferrerRow; canManage: boolean }) {
  return (
    <li
      className={`rounded-[var(--radius-card)] border bg-surface p-4 ${
        row.is_blocked ? "border-warn/50" : "border-line"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-medium">{row.name}</p>
          <p className="text-sm text-muted">
            {row.email} · {row.toke_id} · code{" "}
            <span className="font-mono">{row.code}</span>
          </p>
        </div>
        {row.is_blocked && (
          <span className="rounded-full border border-warn/40 bg-warn/5 px-2.5 py-1 text-xs text-warn">
            Blocked
          </span>
        )}
      </div>

      {row.is_blocked && row.blocked_reason && (
        <p className="mt-2 rounded bg-warn/5 p-2 text-sm text-warn">{row.blocked_reason}</p>
      )}

      <dl className="mt-3 flex flex-wrap gap-x-8 gap-y-2 text-sm">
        <div>
          <dt className="text-xs text-muted">Customers referred</dt>
          <dd>{row.referred_customers}</dd>
        </div>
        {row.balances.length === 0 ? (
          <div>
            <dt className="text-xs text-muted">Balance</dt>
            <dd className="text-muted">Nothing earned yet</dd>
          </div>
        ) : (
          row.balances.map((b) => (
            <div key={b.currency}>
              <dt className="text-xs text-muted">{b.currency} available</dt>
              {/* A negative balance is a real state — a clawback after a payout puts one
                  there — and it is the number that explains why somebody cannot request
                  a payout, so it is called out rather than shown as just another figure. */}
              <dd className={Number(b.available) < 0 ? "text-warn" : ""}>
                {b.available}
                {Number(b.pending) > 0 && (
                  <span className="text-muted"> · {b.pending} pending</span>
                )}
              </dd>
            </div>
          ))
        )}
      </dl>

      <ReferrerActions
        referrer={row}
        canManage={canManage}
        onBlock={setReferrerBlockedAction}
        onAdjust={addAdjustmentAction}
      />
    </li>
  );
}
