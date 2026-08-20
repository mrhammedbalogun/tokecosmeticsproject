"use client";

/**
 * The per-row "Remove" control on the staff roster: two clicks, then the injected
 * Server Function. Two clicks because there is no undo — the account is deactivated,
 * de-roled and its sessions killed the moment the action lands (the API's guards do
 * the real refusing: not yourself, never an Owner).
 *
 * The row's disappearance is not this component's job: the action calls
 * `revalidatePath("/staff")`, so the server re-renders the roster without the member.
 * All this holds locally is the confirm arming, the pending flag and the last error.
 */
import { useState, useTransition } from "react";

const UNREACHABLE = "That did not reach the server — check the connection and retry.";

export function RemoveStaffButton({
  memberId,
  email,
  action,
}: {
  memberId: number;
  email: string;
  /** The Server Function. Injected so the table is testable without a server. */
  action: (memberId: number) => Promise<{ error?: string }>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const onConfirm = () => {
    setConfirming(false);
    setError(null);
    startTransition(async () => {
      // The load-bearing catch: a rejected request must become a message, not an
      // unhandled rejection (same rule as every write in the product editor).
      try {
        const res = await action(memberId);
        setError(res.error ?? null);
      } catch {
        setError(UNREACHABLE);
      }
    });
  };

  return (
    <div>
      {confirming ? (
        <span className="flex items-center gap-1">
          <button
            type="button"
            onClick={onConfirm}
            disabled={pending}
            className="rounded border border-warn/40 bg-warn/10 px-2 py-1 text-xs text-warn"
          >
            Really remove
          </button>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            className="rounded border border-line px-2 py-1 text-xs text-muted hover:border-accent hover:text-foreground"
          >
            Cancel
          </button>
        </span>
      ) : (
        <button
          type="button"
          onClick={() => {
            setError(null);
            setConfirming(true);
          }}
          disabled={pending}
          aria-label={`Remove ${email}`}
          title="Deactivates the account, removes its role and signs it out everywhere"
          className="rounded border border-line px-2 py-1 text-xs text-muted hover:border-warn hover:text-warn disabled:opacity-40"
        >
          {pending ? "Removing…" : "Remove"}
        </button>
      )}
      {error && <p className="mt-1 max-w-48 text-xs text-warn">{error}</p>}
    </div>
  );
}
