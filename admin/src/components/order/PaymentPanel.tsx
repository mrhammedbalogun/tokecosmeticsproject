"use client";

/**
 * The payment panel: what was paid, what is left to refund, and the confirm-receipt
 * ceremony for bank transfer.
 *
 * ── CONFIRMING A TRANSFER IS NOT A VERIFICATION ─────────────────────────────────────
 *
 * `gateway.verify()` raises `ManualVerificationOnly` for bank transfer — there is nothing
 * to ask. **The person reading the bank statement IS the verification**, and the panel says
 * so in those words. There is deliberately no "verify again" control beside it: that means
 * something entirely different for Paystack, and putting the two together would teach an
 * operator that confirming is a lookup rather than a judgement.
 *
 * ── THE TWO OVERRIDES SHOW WHAT THEY ARE OVERRIDING ─────────────────────────────────
 *
 * A discrepancy comes back with both numbers, so the panel shows expected, received AND
 * the delta, and takes the reason inline — the backend forces one. A bare "override?"
 * checkbox would hide the single number the decision is about.
 */
import { useState, useTransition } from "react";
import type { WriteState } from "@/app/(shell)/orders/[number]/actions";
import type { OrderPayment } from "@/lib/order-detail";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export interface PaymentPanelProps {
  number: string;
  payments: OrderPayment[];
  currency: string;
  grandTotal: string;
  confirmReceipt: (input: {
    number: string;
    amountReceived: string;
    bankReference: string;
    note: string;
    acceptDiscrepancy: boolean;
    allowDuplicateReference: boolean;
  }) => Promise<WriteState>;
}

export function PaymentPanel({
  number,
  payments,
  currency,
  grandTotal,
  confirmReceipt,
}: PaymentPanelProps) {
  const [amount, setAmount] = useState(grandTotal);
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [state, setState] = useState<WriteState>({});
  const [pending, start] = useTransition();

  // The bank-transfer goods payment is the one this ceremony is about; the endpoint picks
  // the same one (payments/views.py:247).
  const transfer = payments.find(
    (p) => p.gateway === "bank_transfer" && p.purpose === "goods",
  );
  const awaiting = transfer && !["succeeded", "refunded", "partially_refunded"].includes(
    transfer.status,
  );

  const submit = (overrides: { accept?: boolean; allowDuplicate?: boolean } = {}) =>
    start(async () => {
      setState(
        await confirmReceipt({
          number,
          amountReceived: amount,
          bankReference: reference,
          note,
          acceptDiscrepancy: Boolean(overrides.accept),
          allowDuplicateReference: Boolean(overrides.allowDuplicate),
        }),
      );
    });

  const delta =
    state.expected && state.received
      ? Number(state.received) - Number(state.expected)
      : null;

  return (
    <section className="rounded-[var(--radius-card)] border border-line p-4">
      <h2 className="text-sm font-medium">Payment</h2>

      {payments.length === 0 ? (
        <p className="mt-2 text-sm text-muted">
          No payment recorded. Every migrated legacy order looks like this.
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {payments.map((payment) => (
            <li key={payment.id} className="rounded border border-line p-3 text-sm">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span>
                  <span className="font-medium">{payment.gateway.replace(/_/g, " ")}</span>
                  {payment.purpose !== "goods" && (
                    // A freight receipt is not what refunding this order means — the
                    // refund endpoint picks purpose="goods" for that reason.
                    <span className="ml-2 rounded border border-line px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted">
                      {payment.purpose}
                    </span>
                  )}
                </span>
                <span className="tabular-nums">
                  {payment.amount} {currency}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-muted">
                <span>{payment.status.replace(/_/g, " ")}</span>
                {payment.gateway_reference && (
                  <span className="font-mono">{payment.gateway_reference}</span>
                )}
                <span>refundable {payment.refundable}</span>
              </div>
              {payment.refunds.length > 0 && (
                <ul className="mt-2 space-y-0.5 border-t border-line pt-2 text-xs text-muted">
                  {payment.refunds.map((refund) => (
                    <li key={refund.id}>
                      refunded {refund.amount} — {refund.status}
                      {refund.reason && ` — ${refund.reason}`}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}

      {awaiting && (
        <div className="mt-4 rounded border border-accent/30 bg-accent/5 p-3">
          <h3 className="text-sm font-medium">Confirm the transfer landed</h3>
          <p className="mt-1 text-xs text-muted">
            {/* The whole point, said plainly. */}
            There is nothing to look up — you reading the bank statement is the check.
            Confirming releases the goods.
          </p>

          {state.error && (
            <div className="mt-3 rounded border border-warn/30 bg-warn/5 p-3 text-sm text-warn">
              <p>{state.error}</p>

              {state.code === "amount_discrepancy" && (
                <div className="mt-2">
                  <table className="text-xs tabular-nums">
                    <tbody>
                      <tr>
                        <td className="pr-3">Order total</td>
                        <td>{state.expected}</td>
                      </tr>
                      <tr>
                        <td className="pr-3">You received</td>
                        <td>{state.received}</td>
                      </tr>
                      <tr className="font-medium">
                        <td className="pr-3">Difference</td>
                        <td>
                          {delta !== null && delta > 0 ? "+" : ""}
                          {delta !== null ? delta.toFixed(2) : "—"}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                  <p className="mt-2 text-xs">
                    A reason is required and goes on the order permanently.
                  </p>
                  <button
                    type="button"
                    onClick={() => submit({ accept: true })}
                    disabled={pending || !note.trim()}
                    className="mt-2 rounded border border-warn/40 bg-warn/10 px-3 py-1.5 text-xs font-medium disabled:opacity-40"
                  >
                    Accept the difference and fulfil
                  </button>
                  {!note.trim() && (
                    <span className="ml-2 text-xs">Write a note below first.</span>
                  )}
                </div>
              )}

              {state.code === "duplicate_bank_reference" && (
                <div className="mt-2">
                  <p className="text-xs">
                    {/* Named for what it protects against, because the operator is about
                        to switch it off. */}
                    This reference has already paid for something. Overriding it can ship a
                    second order against one transfer.
                  </p>
                  <button
                    type="button"
                    onClick={() => submit({ allowDuplicate: true })}
                    disabled={pending || !note.trim()}
                    className="mt-2 rounded border border-warn/40 bg-warn/10 px-3 py-1.5 text-xs font-medium disabled:opacity-40"
                  >
                    Use it anyway
                  </button>
                </div>
              )}
            </div>
          )}

          {state.success && (
            <p className="mt-3 rounded border border-ok/30 bg-ok/10 p-2 text-sm text-ok" role="status">
              {state.success}
            </p>
          )}

          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="block text-xs text-muted">
              Amount received
              <input
                type="text"
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                aria-label="Amount received"
                className={`mt-1 ${FIELD} tabular-nums`}
              />
            </label>
            <label className="block text-xs text-muted">
              Bank reference
              <input
                type="text"
                value={reference}
                onChange={(e) => setReference(e.target.value)}
                placeholder="from the statement"
                aria-label="Bank reference"
                className={`mt-1 ${FIELD} font-mono`}
              />
            </label>
            <label className="block text-xs text-muted sm:col-span-2">
              Note
              <input
                type="text"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="anything worth reading back later"
                aria-label="Note"
                className={`mt-1 ${FIELD}`}
              />
            </label>
          </div>

          <button
            type="button"
            onClick={() => submit()}
            disabled={pending}
            className="mt-3 rounded bg-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            {pending ? "Confirming…" : "Confirm payment received"}
          </button>
        </div>
      )}
    </section>
  );
}
