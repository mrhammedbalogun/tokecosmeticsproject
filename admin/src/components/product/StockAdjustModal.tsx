/**
 * The stock adjust modal.
 *
 * THE FIELD IS AN ABSOLUTE COUNT, not a change. `inventory.services.adjust` SETS on-hand
 * and stores the difference as the movement, so the label says "New quantity" and the
 * running delta is shown beside it — "47" means very different things depending on whether
 * the shelf held 12 or 300, and the ledger records the difference either way.
 *
 * REASON AND NOTE ARE BOTH REQUIRED, because the endpoint requires them. That is the
 * point of the endpoint: a stock write-off with no stated reason is exactly the row
 * somebody wants to read back a month later.
 *
 * A PLAIN OVERLAY, not `<dialog>`: `showModal()` needs an effect and a ref to open, and
 * this renders only while it is open, so the imperative half would be pure ceremony.
 * Escape and the backdrop both close it; focus goes to the quantity field on open.
 */
import { useEffect, useRef, useState } from "react";
import {
  deltaFor,
  hasErrors,
  REASON_GROUPS,
  reasonLabel,
  validateAdjust,
  type AdjustErrors,
} from "@/lib/stock-adjust";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export interface StockAdjustModalProps {
  sku: string;
  warehouseName: string;
  currentQuantity: number;
  reserved: number;
  busy: boolean;
  /** From the server, mapped onto fields where it named one. */
  serverErrors: AdjustErrors;
  serverMessage: string | null;
  onSubmit: (values: { quantity: number; reason: string; note: string }) => void;
  onClose: () => void;
}

export function StockAdjustModal({
  sku,
  warehouseName,
  currentQuantity,
  reserved,
  busy,
  serverErrors,
  serverMessage,
  onSubmit,
  onClose,
}: StockAdjustModalProps) {
  const [quantity, setQuantity] = useState(String(currentQuantity));
  const [reason, setReason] = useState("adjustment");
  const [note, setNote] = useState("");
  const [touched, setTouched] = useState(false);
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

  const local = validateAdjust({ quantity, reason, note });
  // Local errors only after a submit attempt — showing "say why" before anybody has had
  // the chance to type is nagging, not helping. Server errors show as soon as they arrive.
  const errors: AdjustErrors = {
    quantity: (touched ? local.quantity : undefined) ?? serverErrors.quantity,
    reason: (touched ? local.reason : undefined) ?? serverErrors.reason,
    note: (touched ? local.note : undefined) ?? serverErrors.note,
  };

  const delta = deltaFor(currentQuantity, quantity);

  const submit = () => {
    setTouched(true);
    if (hasErrors(local)) return;
    onSubmit({ quantity: Number(quantity.trim()), reason, note: note.trim() });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Adjust stock for ${sku}`}
        className="w-full max-w-md rounded-[var(--radius-card)] border border-line bg-background p-5 shadow-lg"
      >
        <h2 className="text-base font-semibold">Adjust stock</h2>
        <p className="mt-1 text-sm text-muted">
          <span className="font-mono">{sku}</span> in {warehouseName} — currently{" "}
          <strong>{currentQuantity}</strong>
          {reserved > 0 && `, ${reserved} held by pending orders`}
        </p>

        {serverMessage && (
          <p className="mt-3 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn">
            {serverMessage}
          </p>
        )}

        <div className="mt-4 space-y-3">
          <label className="block text-xs text-muted">
            New quantity
            <input
              ref={quantityRef}
              type="text"
              inputMode="numeric"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              aria-label="New quantity"
              className={`mt-1 ${FIELD} ${errors.quantity ? "border-warn" : ""}`}
            />
            {/* The count replaces what is there — said plainly, because somebody who reads
                this as "add 47" would set the shelf to 47 and not notice. */}
            <p className="mt-1 text-xs text-muted">
              This replaces the count, it is not added to it.
              {delta !== null && delta !== 0 && (
                <span className={delta > 0 ? " text-ok" : " text-warn"}>
                  {" "}
                  Ledger records {delta > 0 ? `+${delta}` : delta}.
                </span>
              )}
            </p>
            {errors.quantity && <p className="mt-1 text-xs text-warn">{errors.quantity}</p>}
          </label>

          <label className="block text-xs text-muted">
            Reason
            <select
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              aria-label="Reason"
              className={`mt-1 ${FIELD} ${errors.reason ? "border-warn" : ""}`}
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
              placeholder="Counted 3 broken jars"
              aria-label="Note"
              className={`mt-1 ${FIELD} ${errors.note ? "border-warn" : ""}`}
            />
            {errors.note && <p className="mt-1 text-xs text-warn">{errors.note}</p>}
          </label>
        </div>

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-line px-3 py-1.5 text-sm text-muted hover:border-accent hover:text-foreground"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            {busy ? "Saving…" : "Adjust stock"}
          </button>
        </div>
      </div>
    </div>
  );
}
