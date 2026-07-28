"use client";

/**
 * Account creation. Same shape as LoginForm and for the same reasons: native validation
 * left on, submit disabled only while pending (never on empty fields, which would break
 * pre-hydration submits), and the live region present from first paint.
 *
 * The one thing this form does that login must not: when the address already has an
 * account, it says so and offers to sign in. Registration cannot hide that fact — the
 * backend answers "Account already exists" — so the useful move is to act on it rather
 * than show an error the user can do nothing with.
 */
import Link from "next/link";
import { useActionState } from "react";
import type { RegisterState } from "@/app/(auth)/register/actions";
import { TurnstileWidget } from "@/components/auth/TurnstileWidget";

const ERROR_ID = "register-error";

const inputClass =
  "w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm " +
  "focus:outline-none focus:ring-2 focus:ring-accent/40";

export function RegisterForm({
  next,
  action,
  initialState = {},
}: {
  next: string;
  action: (state: RegisterState, formData: FormData) => Promise<RegisterState>;
  initialState?: RegisterState;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const error = state.error;
  const destination = state.next ?? next;

  return (
    <form action={formAction} className="space-y-4">
      <input type="hidden" name="next" value={destination} />

      <div aria-live="polite">
        {error && (
          <p id={ERROR_ID} role="alert" className="text-sm text-red-700">
            {error}{" "}
            {state.emailTaken && (
              <Link
                href={`/login?next=${encodeURIComponent(destination)}`}
                className="underline hover:text-foreground"
              >
                Sign in instead
              </Link>
            )}
          </p>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="register-first-name" className="mb-1 block text-sm font-medium">
            First name
          </label>
          <input
            id="register-first-name"
            name="first_name"
            type="text"
            defaultValue={state.firstName ?? ""}
            required
            autoComplete="given-name"
            autoFocus
            className={inputClass}
          />
        </div>
        <div>
          <label htmlFor="register-last-name" className="mb-1 block text-sm font-medium">
            Last name <span className="text-muted">(optional)</span>
          </label>
          <input
            id="register-last-name"
            name="last_name"
            type="text"
            defaultValue={state.lastName ?? ""}
            autoComplete="family-name"
            className={inputClass}
          />
        </div>
      </div>

      <div>
        <label htmlFor="register-email" className="mb-1 block text-sm font-medium">
          Email
        </label>
        <input
          id="register-email"
          name="email"
          type="email"
          defaultValue={state.email ?? ""}
          required
          autoComplete="email"
          inputMode="email"
          autoCapitalize="none"
          spellCheck={false}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? ERROR_ID : undefined}
          className={inputClass}
        />
      </div>

      <div>
        <label htmlFor="register-password" className="mb-1 block text-sm font-medium">
          Password
        </label>
        <input
          id="register-password"
          name="password"
          type="password"
          required
          autoComplete="new-password"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? ERROR_ID : undefined}
          className={inputClass}
        />
        <p className="mt-1 text-xs text-muted">At least 8 characters.</p>
      </div>

      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          name="marketing_consent"
          defaultChecked={false}
          className="mt-0.5"
        />
        <span className="text-muted">
          Email me offers, launches and beauty tips. You can unsubscribe any time.
        </span>
      </label>

      {/* Injects the hidden cf-turnstile-response input into this form. `state` changes
          identity on every failed submit, which resets the single-use token. */}
      <TurnstileWidget resetSignal={state} />

      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
      >
        {pending ? "Creating your account…" : "Create account"}
      </button>

      <p className="text-sm text-muted">
        Already have an account?{" "}
        <Link
          href={`/login?next=${encodeURIComponent(destination)}`}
          className="underline hover:text-foreground"
        >
          Sign in
        </Link>
      </p>
    </form>
  );
}
