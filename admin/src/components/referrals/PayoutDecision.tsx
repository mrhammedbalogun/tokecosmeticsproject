"use client";

import { useState, useTransition } from "react";
import type { PayoutActionState } from "@/app/(shell)/referrals/actions";
import type { PayoutRow } from "@/lib/referrals";

/**
 * The decision controls on one payout row.
 *
 * ── WHY REJECT AND MARK-PAID BOTH OPEN A PANEL ──────────────────────────────────────
 *
 * Neither is a one-click action, and not for ceremony's sake: each needs a field that
 * the shop cannot reconstruct afterwards. Rejecting needs the sentence the customer will
 * read on their payouts page — without it they get a refusal with no reason and the desk
 * gets a ticket. Marking paid needs the bank's transfer reference, which is the only
 * artefact that answers "I never received it" months later.
 *
 * Approve takes no required field, so it is a single button. That asymmetry is the point:
 * the two irreversible-ish actions ask for something, the reversible one does not.
 *
 * ── WHAT THIS COMPONENT DOES NOT DECIDE ─────────────────────────────────────────────
 *
 * Whether the viewer may pay. `canPay` is passed in from the server's scope list purely
 * so the button is not dangled in front of a Manager who will only get a 403 — the
 * enforcement is `referrals.pay` on the endpoint, and re-deciding it here would put a
 * second, weaker copy of the rule in a bundle anyone can read.
 */
export function PayoutDecision({
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
  const [panel, setPanel] = useState<"none" | "reject" | "paid">("none");
  const [customerMessage, setCustomerMessage] = useState("");
  const [reference, setReference] = useState("");
  const [adminNote, setAdminNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  // `paid` and `rejected` are terminal. Money has moved, or the commissions have already
  // gone back to the referrer's balance; either way there is nothing left to decide here.
  const open = row.status === "requested" || row.status === "approved";
  if (!open) return null;
  if (!canDecide && !canPay) {
    return (
      <p className="text-xs text-muted">
        Read-only — your role can see this request but not decide it.
      </p>
    );
  }

  const run = (fn: () => Promise<PayoutActionState>) => {
    setError(null);
    startTransition(async () => {
      const result = await fn();
      if (result.message) {
        setError(result.message);
        return;
      }
      setPanel("none");
      setCustomerMessage("");
      setReference("");
      setAdminNote("");
    });
  };

  const BTN =
    "rounded border px-3 py-1.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-60";
  const FIELD =
    "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none";

  return (
    <div className="mt-3 border-t border-line pt-3">
      {panel === "none" && (
        <div className="flex flex-wrap gap-2">
          {canDecide && row.status === "requested" && (
            <button
              type="button"
              disabled={pending}
              onClick={() => run(() => onApprove({ id: row.id, adminNote: "" }))}
              className={`${BTN} border-line hover:border-accent hover:text-accent`}
            >
              Approve
            </button>
          )}
          {canPay && (
            <button
              type="button"
              disabled={pending}
              onClick={() => setPanel("paid")}
              className={`${BTN} border-accent bg-accent text-surface hover:bg-accent-strong`}
            >
              Mark paid
            </button>
          )}
          {canDecide && (
            <button
              type="button"
              disabled={pending}
              onClick={() => setPanel("reject")}
              className={`${BTN} border-line text-muted hover:border-warn hover:text-warn`}
            >
              Reject
            </button>
          )}
        </div>
      )}

      {panel === "paid" && (
        <div className="grid gap-2">
          <label className="block text-xs text-muted">
            Bank transfer reference
            <input
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="e.g. GTB/2026/0042"
              className={`mt-1 ${FIELD}`}
            />
          </label>
          <p className="text-xs text-muted">
            Confirm the transfer has actually left the account. The customer is emailed
            this reference.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={pending || !reference.trim()}
              onClick={() =>
                run(() => onMarkPaid({ id: row.id, reference, adminNote }))
              }
              className={`${BTN} border-accent bg-accent text-surface hover:bg-accent-strong`}
            >
              {pending ? "Saving…" : "Confirm paid"}
            </button>
            <button
              type="button"
              disabled={pending}
              onClick={() => setPanel("none")}
              className={`${BTN} border-line text-muted`}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {panel === "reject" && (
        <div className="grid gap-2">
          <label className="block text-xs text-muted">
            What the customer will see
            <textarea
              value={customerMessage}
              onChange={(e) => setCustomerMessage(e.target.value)}
              rows={2}
              placeholder="e.g. The account name does not match your account holder name."
              className={`mt-1 ${FIELD}`}
            />
          </label>
          <p className="text-xs text-muted">
            Rejecting returns the commission to their available balance — they can request
            again once this is sorted out.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={pending || !customerMessage.trim()}
              onClick={() =>
                run(() => onReject({ id: row.id, customerMessage, adminNote }))
              }
              className={`${BTN} border-warn text-warn hover:bg-warn/5`}
            >
              {pending ? "Saving…" : "Confirm reject"}
            </button>
            <button
              type="button"
              disabled={pending}
              onClick={() => setPanel("none")}
              className={`${BTN} border-line text-muted`}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="mt-2 text-sm text-warn">
          {error}
        </p>
      )}
    </div>
  );
}
