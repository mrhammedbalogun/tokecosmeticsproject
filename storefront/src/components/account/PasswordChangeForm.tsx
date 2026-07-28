"use client";

import { useActionState } from "react";
import type { PasswordChangeState } from "@/app/(shop)/account/security/actions";

const ERROR_ID = "password-change-error";

const inputClass =
  "w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm " +
  "focus:outline-none focus:ring-2 focus:ring-accent/40";

export function PasswordChangeForm({
  action,
  initialState = {},
}: {
  action: (state: PasswordChangeState, formData: FormData) => Promise<PasswordChangeState>;
  initialState?: PasswordChangeState;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const error = state.error;

  return (
    <form action={formAction} className="max-w-md space-y-4">
      <div aria-live="polite">
        {error && (
          <p id={ERROR_ID} role="alert" className="text-sm text-red-700">
            {error}
          </p>
        )}
        {state.changed && !error && (
          <p className="text-sm text-accent-strong">
            Password updated. You stay signed in on this device.
          </p>
        )}
      </div>

      <div>
        <label htmlFor="pw-current" className="mb-1 block text-sm font-medium">
          Current password
        </label>
        <input
          id="pw-current"
          name="old_password"
          type="password"
          required
          autoComplete="current-password"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? ERROR_ID : undefined}
          className={inputClass}
        />
      </div>

      <div>
        <label htmlFor="pw-new" className="mb-1 block text-sm font-medium">
          New password
        </label>
        <input
          id="pw-new"
          name="new_password"
          type="password"
          required
          autoComplete="new-password"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? ERROR_ID : undefined}
          className={inputClass}
        />
      </div>

      <div>
        <label htmlFor="pw-confirm" className="mb-1 block text-sm font-medium">
          Repeat new password
        </label>
        <input
          id="pw-confirm"
          name="confirm"
          type="password"
          required
          autoComplete="new-password"
          className={inputClass}
        />
      </div>

      <button
        type="submit"
        disabled={pending}
        className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
      >
        {pending ? "Updating…" : "Update password"}
      </button>
    </form>
  );
}
