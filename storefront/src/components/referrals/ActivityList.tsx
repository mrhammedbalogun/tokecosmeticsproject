/**
 * The earnings feed: every referred order, and every correction to the balance.
 *
 * A LIST OF CARDS, NOT A TABLE, and that is a deliberate reversal of the obvious choice.
 * The rows carry six fields, two of which are long sentences ("Ready in 41 days",
 * "order TC-100042 refunded after commission was paid out"). A six-column table either
 * scrolls sideways on a phone — where most of this audience reads — or truncates the
 * sentence that explains why the money is not there yet, which is the only field a
 * confused referrer actually needs.
 *
 * Commissions and adjustments are interleaved by date rather than split into two lists:
 * a referrer whose balance dropped is looking for the reason at the top of one list, not
 * in a second section further down the page.
 */
import {
  type Adjustment,
  type Commission,
  formatReferralDate,
  holdingLabel,
} from "@/lib/referrals";

type Row =
  | { kind: "commission"; at: string; data: Commission }
  | { kind: "adjustment"; at: string; data: Adjustment };

export function ActivityList({
  commissions,
  adjustments,
  holdDays,
}: {
  commissions: Commission[];
  adjustments: Adjustment[];
  holdDays: number;
}) {
  const rows: Row[] = [
    ...commissions.map((c): Row => ({ kind: "commission", at: c.placed_at, data: c })),
    ...adjustments.map((a): Row => ({ kind: "adjustment", at: a.created_at, data: a })),
  ].sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());

  if (rows.length === 0) {
    return (
      <p className="rounded-[var(--radius-card)] border border-dashed border-line p-8 text-center text-sm text-muted">
        No earnings yet. Share your link and the first order will show up here.
      </p>
    );
  }

  return (
    <ul className="space-y-3">
      {rows.map((row) =>
        row.kind === "commission" ? (
          <CommissionRow key={`c${row.data.id}`} commission={row.data} holdDays={holdDays} />
        ) : (
          <AdjustmentRow key={`a${row.data.id}`} adjustment={row.data} />
        ),
      )}
    </ul>
  );
}

function CommissionRow({
  commission,
  holdDays,
}: {
  commission: Commission;
  holdDays: number;
}) {
  const reversed = commission.status === "reversed";
  const holding = holdingLabel(commission, holdDays);

  return (
    <li className="rounded-[var(--radius-card)] border border-line bg-surface p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="font-medium">
          {commission.customer_label}
          <span className="font-normal text-muted"> ordered</span>
        </p>
        <p
          className={
            "font-display text-lg " +
            (reversed ? "text-muted line-through" : "text-accent-strong")
          }
        >
          {commission.amount_display}
        </p>
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
        <span>{formatReferralDate(commission.placed_at)}</span>
        <span aria-hidden>·</span>
        <span className="font-mono text-xs">{commission.order_number}</span>
        <span aria-hidden>·</span>
        {/* The maths, shown rather than asserted: "10% of ₦24,000" is the line that stops
            a referrer emailing to ask why their cut is not 10% of what their friend paid
            (it excludes delivery and tax). */}
        <span>
          {trimPercent(commission.rate_percent)}% of {commission.base_amount_display}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <StatusChip status={commission.status} label={commission.status_label} />
        {holding && <span className="text-sm text-muted">{holding}</span>}
        {reversed && commission.reversed_reason && (
          <span className="text-sm text-muted">{commission.reversed_reason}</span>
        )}
      </div>
    </li>
  );
}

function AdjustmentRow({ adjustment }: { adjustment: Adjustment }) {
  const credit = Number(adjustment.amount) >= 0;
  return (
    <li className="rounded-[var(--radius-card)] border border-line bg-beige/60 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="font-medium">
          {credit ? "Bonus added" : "Adjustment"}
        </p>
        <p className={"font-display text-lg " + (credit ? "text-accent-strong" : "text-red-700")}>
          {adjustment.amount_display}
        </p>
      </div>
      <p className="mt-1 text-sm text-muted">
        {formatReferralDate(adjustment.created_at)} · {adjustment.reason}
      </p>
      {adjustment.settled && (
        <p className="mt-1 text-xs text-muted">Already settled against a past payout.</p>
      )}
    </li>
  );
}

/** "10.00" → "10", but "12.50" stays. The rate is a Decimal string because it is
 * money-adjacent; "10.00% of ₦45,000.00" in a sentence reads like a report, not a
 * receipt. Kept identical to the dashboard's own trimPercent — both exist because the
 * API cannot know whether a caller is rendering prose or doing arithmetic. */
function trimPercent(raw: string): string {
  return raw.replace(/\.0+$/, "");
}

const CHIP: Record<string, string> = {
  pending: "bg-beige text-muted",
  available: "bg-accent/10 text-accent-strong",
  paid: "bg-accent/10 text-accent-strong",
  reversed: "bg-red-50 text-red-700",
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
