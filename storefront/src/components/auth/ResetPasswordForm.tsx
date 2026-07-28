"use client";

/**
 * The new-password form. uid+token arrive as hidden inputs from the page (which read
 * them from the emailed link's query string) and are re-validated in the action —
 * hidden inputs are client-supplied. On success the form is replaced by a sign-in
 * prompt: the token is spent, so leaving the form up invites a confusing second
 * submit that can only fail.
 */
import Link from "next/link";
import { useActionState } from "react";
import type { ResetState } from "@/app/(auth)/reset-password/actions";

const ERROR_ID = "reset-error";

const inputClass =
  "w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm " +
  "focus:outline-none focus:ring-2 focus:ring-accent/40";

export function ResetPasswordForm({
  uid,
  token,
  action,
  initialState = {},
}: {
  uid: string;
  token: string;
  action: (state: ResetState, formData: FormData) => Promise<ResetState>;
  initialState?: ResetState;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const error = state.error;

  if (state.done) {
    return (
      <div aria-live="polite">
        <p className="text-sm">Your password has been updated.</p>
        <p className="mt-4 text-sm">
          <Link href="/login" className="underline hover:text-foreground">
            Sign in with your new password
          </Link>
        </p>
      </div>
    );
  }

  return (
    <form action={formAction} className="space-y-4">
      <input type="hidden" name="uid" value={uid} />
      <input type="hidden" name="token" value={token} />

      <div aria-live="polite">
        {error && (
          <p id={ERROR_ID} role="alert" className="text-sm text-red-700">
            {error}
          </p>
        )}
      </div>

      <div>
        <label htmlFor="reset-password" className="mb-1 block text-sm font-medium">
          New password
        </label>
        <input
          id="reset-password"
          name="password"
          type="password"
          required
          autoComplete="new-password"
          autoFocus
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? ERROR_ID : undefined}
          className={inputClass}
        />
      </div>

      <div>
        <label htmlFor="reset-confirm" className="mb-1 block text-sm font-medium">
          Repeat new password
        </label>
        <input
          id="reset-confirm"
          name="confirm"
          type="password"
          required
          autoComplete="new-password"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? ERROR_ID : undefined}
          className={inputClass}
        />
      </div>

      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
      >
        {pending ? "Saving…" : "Set new password"}
      </button>
    </form>
  );
}
