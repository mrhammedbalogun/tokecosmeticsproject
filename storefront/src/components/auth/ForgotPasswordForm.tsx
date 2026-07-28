"use client";

/**
 * The request-reset form, following LoginForm's conventions: client component only
 * for pending/error state, submission is a Server Function, native validation stays
 * on, and the live region exists from first paint. On success the form is REPLACED
 * by the confirmation copy — resubmitting "did it send?" only burns the 5/hour
 * per-email throttle that protects the address from email-bombing.
 */
import Link from "next/link";
import { useActionState } from "react";
import type { ForgotState } from "@/app/(auth)/forgot-password/actions";
import { TurnstileWidget } from "@/components/auth/TurnstileWidget";

const ERROR_ID = "forgot-error";

const inputClass =
  "w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm " +
  "focus:outline-none focus:ring-2 focus:ring-accent/40";

export function ForgotPasswordForm({
  action,
  initialState = {},
}: {
  action: (state: ForgotState, formData: FormData) => Promise<ForgotState>;
  initialState?: ForgotState;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const error = state.error;

  if (state.sent) {
    return (
      <div aria-live="polite">
        <p className="text-sm">
          If an account exists for <span className="font-medium">{state.email}</span>, a
          reset link is on its way. Check your inbox (and the spam folder) — the link
          works once and expires.
        </p>
        <p className="mt-4 text-sm text-muted">
          <Link href="/login" className="underline hover:text-foreground">
            Back to sign in
          </Link>
        </p>
      </div>
    );
  }

  return (
    <form action={formAction} className="space-y-4">
      <div aria-live="polite">
        {error && (
          <p id={ERROR_ID} role="alert" className="text-sm text-red-700">
            {error}
          </p>
        )}
      </div>

      <div>
        <label htmlFor="forgot-email" className="mb-1 block text-sm font-medium">
          Email
        </label>
        <input
          id="forgot-email"
          name="email"
          type="email"
          defaultValue={state.email ?? ""}
          required
          autoComplete="email"
          inputMode="email"
          autoCapitalize="none"
          spellCheck={false}
          autoFocus
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? ERROR_ID : undefined}
          className={inputClass}
        />
      </div>

      {/* Injects the hidden cf-turnstile-response input; `state` changes identity on
          every failed submit, which resets the single-use token. */}
      <TurnstileWidget resetSignal={state} />

      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
      >
        {pending ? "Sending…" : "Email me a reset link"}
      </button>

      <p className="text-sm text-muted">
        Remembered it?{" "}
        <Link href="/login" className="underline hover:text-foreground">
          Sign in
        </Link>
      </p>
    </form>
  );
}
