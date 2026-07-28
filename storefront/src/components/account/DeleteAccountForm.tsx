"use client";

/**
 * Account deletion behind a two-step reveal: the form with its password and typed
 * DELETE confirmation only appears after an explicit click, so the destructive path
 * is never one accidental submit away. The action re-checks the phrase server-side —
 * this component is UX, not the guard.
 */
import { useActionState, useState } from "react";
import type { DeleteAccountState } from "@/app/(shop)/account/security/actions";

const ERROR_ID = "delete-account-error";

const inputClass =
  "w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm " +
  "focus:outline-none focus:ring-2 focus:ring-accent/40";

export function DeleteAccountForm({
  action,
  initialState = {},
}: {
  action: (state: DeleteAccountState, formData: FormData) => Promise<DeleteAccountState>;
  initialState?: DeleteAccountState;
}) {
  const [revealed, setRevealed] = useState(false);
  const [state, formAction, pending] = useActionState(action, initialState);
  const error = state.error;

  if (!revealed) {
    return (
      <div>
        <p className="text-sm text-muted">
          Deleting your account signs you out everywhere immediately. Your data is
          removed after 30 days.
        </p>
        <button
          type="button"
          onClick={() => setRevealed(true)}
          className="mt-3 rounded-[var(--radius-card)] border border-red-700 px-4 py-2 text-sm text-red-700 transition-colors hover:bg-red-50"
        >
          Delete my account
        </button>
      </div>
    );
  }

  return (
    <form action={formAction} className="max-w-md space-y-4">
      <div aria-live="polite">
        {error && (
          <p id={ERROR_ID} role="alert" className="text-sm text-red-700">
            {error}
          </p>
        )}
      </div>

      <div>
        <label htmlFor="delete-password" className="mb-1 block text-sm font-medium">
          Your password
        </label>
        <input
          id="delete-password"
          name="password"
          type="password"
          required
          autoComplete="current-password"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? ERROR_ID : undefined}
          className={inputClass}
        />
      </div>

      <div>
        <label htmlFor="delete-phrase" className="mb-1 block text-sm font-medium">
          Type DELETE to confirm
        </label>
        <input
          id="delete-phrase"
          name="confirm_phrase"
          type="text"
          required
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          className={inputClass}
        />
      </div>

      <div className="flex gap-3">
        <button
          type="submit"
          disabled={pending}
          className="rounded-[var(--radius-card)] bg-red-700 px-4 py-2 text-sm text-white transition-colors hover:bg-red-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {pending ? "Deleting…" : "Permanently delete"}
        </button>
        <button
          type="button"
          onClick={() => setRevealed(false)}
          className="text-sm text-muted underline hover:text-foreground"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
