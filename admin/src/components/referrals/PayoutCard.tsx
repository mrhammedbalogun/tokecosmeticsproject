import {
  PAYOUT_AGING_DAYS,
  STATUS_LABEL,
  hasWithholding,
  isAging,
  payoutAmount,
  type PayoutRow,
} from "@/lib/referrals";
import { PayoutDecision } from "@/components/referrals/PayoutDecision";
import type { PayoutActionState } from "@/app/(shell)/referrals/actions";

/**
 * One payout request, as a card rather than a table row.
 *
 * A table was the obvious shape and it is the wrong one here. The person working this
 * queue has to copy four separate bank fields into a banking app without transposing a
 * digit, and read a variable-length list of fraud flags while doing it — both of which a
 * row of narrow cells makes harder. Nine or ten of these exist a month. Cards.
 */

const CHIP: Record<string, string> = {
  requested: "border-line bg-surface text-muted",
  approved: "border-accent/30 bg-accent/10 text-accent",
  paid: "border-ok/30 bg-ok/10 text-ok",
  rejected: "border-line bg-surface text-muted",
};

function Field({ label, value, mono = false }: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={`text-sm ${mono ? "font-mono tracking-wide" : ""}`}>{value || "—"}</dd>
    </div>
  );
}

export function PayoutCard({
  row,
  canDecide,
  canPay,
  onApprove,
  onReject,
  onMarkPaid,
}: {
  row: PayoutRow;
  canDecide: boolean;
  canPay: boolean;
  onApprove: (input: { id: number; adminNote: string }) => Promise<PayoutActionState>;
  onReject: (input: {
    id: number;
    customerMessage: string;
    adminNote: string;
  }) => Promise<PayoutActionState>;
  onMarkPaid: (input: {
    id: number;
    reference: string;
    adminNote: string;
  }) => Promise<PayoutActionState>;
}) {
  const aging = isAging(row);
  return (
    <li
      className={`rounded-[var(--radius-card)] border bg-surface p-4 ${
        aging ? "border-warn/50" : "border-line"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-medium">{payoutAmount(row)}</p>
          {hasWithholding(row) && (
            /* Only when a deduction was actually taken. The gross stays the headline —
               it is what the referrer earned and what the commissions add up to — and
               this line says what will leave the bank instead. */
            <p className="text-sm text-warn">
              Send {row.currency} {row.net_amount} — {row.wht_rate_percent}% withheld (
              {row.currency} {row.wht_amount})
            </p>
          )}
          <p className="text-sm text-muted">
            {row.referrer_name} · {row.referrer_email} · {row.referrer_toke_id}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {row.referrer_is_blocked && (
            <span className="rounded-full border border-warn/40 bg-warn/5 px-2.5 py-1 text-xs text-warn">
              Referrer blocked
            </span>
          )}
          <span
            className={`rounded-full border px-2.5 py-1 text-xs ${CHIP[row.status] ?? CHIP.requested}`}
          >
            {STATUS_LABEL[row.status]}
          </span>
        </div>
      </div>

      {row.days_open !== null && (
        <p className={`mt-2 text-xs ${aging ? "text-warn" : "text-muted"}`}>
          {/* The only place anyone can see how long a person has been waiting: the
              customer's own screen says "we're reviewing it" and nothing else. */}
          Waiting {row.days_open} day{row.days_open === 1 ? "" : "s"}
          {aging ? ` — past the ${PAYOUT_AGING_DAYS}-day mark` : ""}
        </p>
      )}

      {row.flags.length > 0 && (
        <ul className="mt-3 space-y-1 rounded border border-warn/30 bg-warn/5 p-3 text-sm text-warn">
          {/* Signals for a human, never a block — a flagged payout is often perfectly
              honest, and the reviewer is the only one who can tell by asking. */}
          {row.flags.map((flag) => (
            <li key={flag}>• {flag}</li>
          ))}
        </ul>
      )}

      <dl className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Bank" value={row.bank_name} />
        <Field label="Account name" value={row.account_name} />
        <Field label="Account number" value={row.account_number} mono />
        <Field
          label="Orders"
          value={`${row.commission_count} order${row.commission_count === 1 ? "" : "s"}`}
        />
      </dl>

      {(row.reference || row.decided_by_email) && (
        <p className="mt-3 text-xs text-muted">
          {row.reference && <>Reference {row.reference}. </>}
          {row.decided_by_email && <>Decided by {row.decided_by_email}.</>}
        </p>
      )}

      {row.customer_message && (
        <p className="mt-2 rounded bg-beige p-2 text-sm">
          Told the customer: {row.customer_message}
        </p>
      )}

      <PayoutDecision
        row={row}
        canDecide={canDecide}
        canPay={canPay}
        onApprove={onApprove}
        onReject={onReject}
        onMarkPaid={onMarkPaid}
      />
    </li>
  );
}
