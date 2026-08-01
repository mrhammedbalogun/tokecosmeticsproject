"use client";

/**
 * "Start stocking here" — the modal behind an absent cell. Plan-17c Task 4.
 *
 * IT IS NOT THE ADJUST MODAL, and the difference is worth keeping visible. Adjusting
 * answers "what is on the shelf now" for a place that already stocks the thing. This
 * answers "we are going to stock this here", which additionally sets the low-stock
 * threshold and, unlike an adjustment, is legitimately allowed to be ZERO — "we stock
 * this here but hold none today" is a real state and a common one when a warehouse is
 * first opened.
 *
 * So the reason and note are required only when the opening count is above zero: there is
 * no movement to explain when nothing moved, and demanding a note for a 0 would train
 * people to type "n/a" into the field the ledger depends on.
 *
 * A PLAIN OVERLAY, matching `StockAdjustModal` — see that file for why `<dialog>` is not
 * used. Escape and the backdrop both close it; focus starts on the opening count.
 */
import { useEffect, useRef, useState } from "react";
import { REASON_GROUPS, reasonLabel } from "@/lib/stock-adjust";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export interface StartStockingValues {
  quantity: number;
  threshold: number;
  reason: string;
  note: string;
}

export function StartStockingModal({
  sku,
  productName,
  warehouseName,
  busy,
  errors,
  message,
  onSubmit,
  onClose,
}: {
  sku: string;
  productName: string;
  warehouseName: string;
  busy: boolean;
  errors: { quantity?: string; threshold?: string; reason?: string; note?: string };
  message: string | null;
  onSubmit: (values: StartStockingValues) => void;
  onClose: () => void;
}) {
  const [quantity, setQuantity] = useState("0");
  const [threshold, setThreshold] = useState("5");
  const [reason, setReason] = useState("restock");
  const [note, setNote] = useState("");
  const quantityRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    quantityRef.current?.focus();
    quantityRef.current?.select();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const opening = Number(quantity);
  const needsReason = Number.isFinite(opening) && opening > 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form
        className="w-full max-w-md rounded-[var(--radius-card)] border border-line bg-bg p-4 shadow-lg"
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit({
            quantity: Number(quantity),
            threshold: Number(threshold),
            reason,
            note,
          });
        }}
      >
        <h2 className="text-base font-semibold">Start stocking here</h2>
        <p className="mt-1 text-sm text-muted">
          <span className="font-mono">{sku}</span> — {productName} in{" "}
          <strong className="text-fg">{warehouseName}</strong>. There is no stock row here
          yet.
        </p>

        {message && (
          <p className="mt-3 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
            {message}
          </p>
        )}

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="block text-xs text-muted">
            Opening count
            <input
              ref={quantityRef}
              type="text"
              inputMode="numeric"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              className={`mt-1 ${FIELD}`}
            />
            <span className="mt-1 block text-xs text-muted">
              0 is fine — it records that this warehouse stocks the item.
            </span>
            {errors.quantity && <p className="mt-1 text-xs text-warn">{errors.quantity}</p>}
          </label>

          <label className="block text-xs text-muted">
            Low-stock threshold
            <input
              type="text"
              inputMode="numeric"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              className={`mt-1 ${FIELD}`}
            />
            <span className="mt-1 block text-xs text-muted">
              Flagged at or below this count.
            </span>
            {errors.threshold && <p className="mt-1 text-xs text-warn">{errors.threshold}</p>}
          </label>
        </div>

        {needsReason && (
          <div className="mt-3 space-y-3">
            <label className="block text-xs text-muted">
              Reason
              <select
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className={`mt-1 ${FIELD}`}
              >
                {REASON_GROUPS.map((group) => (
                  <optgroup key={group.label} label={group.label}>
                    {group.reasons.map((value) => (
                      <option key={value} value={value}>
                        {reasonLabel(value)}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
              {errors.reason && <p className="mt-1 text-xs text-warn">{errors.reason}</p>}
            </label>

            <label className="block text-xs text-muted">
              Note
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={2}
                placeholder="Where this stock came from"
                className={`mt-1 ${FIELD}`}
              />
              {errors.note && <p className="mt-1 text-xs text-warn">{errors.note}</p>}
            </label>
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            {busy ? "Saving…" : "Start stocking"}
          </button>
        </div>
      </form>
    </div>
  );
}
