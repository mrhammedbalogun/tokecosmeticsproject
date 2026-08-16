"use client";

import { useState, useTransition } from "react";
import type { ReferrerActionState } from "@/app/(shell)/referrals/referrers/actions";
import {
  ADJUSTMENT_KINDS,
  ADJUSTMENT_KIND_LABEL,
  type AdjustmentKind,
  type ReferrerRow,
} from "@/lib/referrals";

/**
 * Block / unblock, and the hand-written adjustment form.
 *
 * ── THE SIGN IS THE INTERFACE ───────────────────────────────────────────────────────
 *
 * The amount field takes a SIGNED number and there is no direction dropdown beside it.
 * A select saying "add / subtract" reads as friendlier and is worse: it splits the
 * meaning of the row across two controls, and the failure mode — crediting what you
 * meant to claw back — looks completely normal until somebody reconciles the month. One
 * field, with the sign in it, and a preview underneath that says in words what is about
 * to happen.
 *
 * ── WHY BOTH ACTIONS SIT BEHIND A PANEL ─────────────────────────────────────────────
 *
 * Neither is one-click. Blocking needs a reason (the backend refuses without one) and an
 * adjustment needs both a reason and an amount. Nothing here is undoable by pressing the
 * same button again: unblocking restores earning but does not un-say anything, and there
 * is no delete for an adjustment — a wrong one is corrected by writing its opposite,
 * which is what a ledger is.
 */
export function ReferrerActions({
  referrer,
  canManage,
  onBlock,
  onAdjust,
}: {
  referrer: ReferrerRow;
  canManage: boolean;
  onBlock: (input: {
    id: number;
    blocked: boolean;
    reason: string;
  }) => Promise<ReferrerActionState>;
  onAdjust: (input: {
    id: number;
    currency: string;
    amount: string;
    kind: string;
    reason: string;
  }) => Promise<ReferrerActionState>;
}) {
  const [panel, setPanel] = useState<"none" | "block" | "adjust">("none");
  const [reason, setReason] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState(referrer.balances[0]?.currency ?? "NGN");
  const [kind, setKind] = useState<AdjustmentKind>("correction");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  if (!canManage) {
    return (
      <p className="text-xs text-muted">
        Read-only — your role can see referrers but not block them or move a balance.
      </p>
    );
  }

  const run = (fn: () => Promise<ReferrerActionState>) => {
    setError(null);
    startTransition(async () => {
      const result = await fn();
      if (result.message) {
        setError(result.message);
        return;
      }
      setPanel("none");
      setReason("");
      setAmount("");
    });
  };

  const BTN =
    "rounded border px-3 py-1.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-60";
  const FIELD =
    "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none";

  const parsed = Number(amount);
  const preview =
    amount.trim() && Number.isFinite(parsed) && parsed !== 0
      ? parsed < 0
        ? `Takes ${currency} ${Math.abs(parsed).toLocaleString("en-NG", { minimumFractionDigits: 2 })} OFF this referrer's balance.`
        : `Adds ${currency} ${parsed.toLocaleString("en-NG", { minimumFractionDigits: 2 })} TO this referrer's balance.`
      : "Negative takes money away, positive gives it.";

  return (
    <div className="mt-3 border-t border-line pt-3">
      {panel === "none" && (
        <div className="flex flex-wrap gap-2">
          {referrer.is_blocked ? (
            <button
              type="button"
              disabled={pending}
              onClick={() => run(() => onBlock({ id: referrer.id, blocked: false, reason: "" }))}
              className={`${BTN} border-line hover:border-accent hover:text-accent`}
            >
              Unblock
            </button>
          ) : (
            <button
              type="button"
              disabled={pending}
              onClick={() => setPanel("block")}
              className={`${BTN} border-line text-muted hover:border-warn hover:text-warn`}
            >
              Block
            </button>
          )}
          <button
            type="button"
            disabled={pending}
            onClick={() => setPanel("adjust")}
            className={`${BTN} border-line hover:border-accent hover:text-accent`}
          >
            Adjust balance
          </button>
        </div>
      )}

      {panel === "block" && (
        <div className="grid gap-2">
          <label className="block text-xs text-muted">
            Why are you blocking them?
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
              placeholder="e.g. Six orders in a week, all shipped to their own address."
              className={`mt-1 ${FIELD}`}
            />
          </label>
          <p className="text-xs text-muted">
            Stops new commission and new payout requests. Does <strong>not</strong> touch
            money already earned, and does not decide an open payout — reject that
            separately if you mean to.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={pending || !reason.trim()}
              onClick={() => run(() => onBlock({ id: referrer.id, blocked: true, reason }))}
              className={`${BTN} border-warn text-warn hover:bg-warn/5`}
            >
              {pending ? "Saving…" : "Confirm block"}
            </button>
            <button type="button" disabled={pending} onClick={() => setPanel("none")}
                    className={`${BTN} border-line text-muted`}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {panel === "adjust" && (
        <div className="grid gap-2">
          <div className="grid gap-2 sm:grid-cols-3">
            <label className="block text-xs text-muted">
              Currency
              <select
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
                className={`mt-1 ${FIELD}`}
              >
                {/* The currencies this referrer actually has a balance in, plus naira as
                    the floor — a first adjustment can precede any earnings. */}
                {Array.from(
                  new Set([...referrer.balances.map((b) => b.currency), "NGN"]),
                ).map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </label>
            <label className="block text-xs text-muted">
              Amount (signed)
              <input
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                inputMode="decimal"
                placeholder="-2500.00"
                className={`mt-1 ${FIELD}`}
              />
            </label>
            <label className="block text-xs text-muted">
              Kind
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value as AdjustmentKind)}
                className={`mt-1 ${FIELD}`}
              >
                {ADJUSTMENT_KINDS.map((k) => (
                  <option key={k} value={k}>{ADJUSTMENT_KIND_LABEL[k]}</option>
                ))}
              </select>
            </label>
          </div>
          <p className={`text-xs ${parsed < 0 ? "text-warn" : "text-muted"}`}>{preview}</p>
          <label className="block text-xs text-muted">
            Reason
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
              placeholder="e.g. Refund on TC-100093 landed after the payout went."
              className={`mt-1 ${FIELD}`}
            />
          </label>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={pending || !reason.trim() || !amount.trim()}
              onClick={() =>
                run(() => onAdjust({ id: referrer.id, currency, amount, kind, reason }))
              }
              className={`${BTN} border-accent bg-accent text-surface hover:bg-accent-strong`}
            >
              {pending ? "Saving…" : "Write adjustment"}
            </button>
            <button type="button" disabled={pending} onClick={() => setPanel("none")}
                    className={`${BTN} border-line text-muted`}>
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
