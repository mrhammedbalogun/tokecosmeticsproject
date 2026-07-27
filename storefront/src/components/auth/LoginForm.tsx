"use client";

/**
 * The sign-in form. A client component only so it can show a pending state and an error
 * without a full reload — the submission itself is a Server Function, so this form works
 * with JavaScript disabled too.
 *
 * Three choices here are deliberate and differ from checkout's SignInStep, which is a
 * checkout step rather than a standalone page:
 *  - native validation stays ON (no `noValidate`): with JS off, `required` and
 *    `type="email"` are the only validation there is;
 *  - submit is disabled on `pending` only, never on empty fields — disabling it on empty
 *    input makes the form unsubmittable before hydration, which defeats the point;
 *  - the live region is in the DOM from first paint, because a region inserted at the same
 *    moment as its content frequently is not announced.
 */
import Link from "next/link";
import { useActionState } from "react";
import type { LoginState } from "@/app/(auth)/login/actions";

const ERROR_ID = "login-error";

const inputClass =
  "w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm " +
  "focus:outline-none focus:ring-2 focus:ring-accent/40";

export function LoginForm({
  next,
  action,
  initialState = {},
}: {
  /** Already sanitised by the page; re-validated server-side in the action regardless. */
  next: string;
  action: (state: LoginState, formData: FormData) => Promise<LoginState>;
  initialState?: LoginState;
}) {
  const [state, formAction, pending] = useActionState(action, initialState);
  const error = state.error;

  return (
    <form action={formAction} className="space-y-4">
      {/* Re-validated in the action: a hidden input is client-supplied, not a trust boundary. */}
      <input type="hidden" name="next" value={state.next ?? next} />

      {/* Present on first render so the error is announced when it arrives. */}
      <div aria-live="polite">
        {error && (
          <p id={ERROR_ID} role="alert" className="text-sm text-red-700">
            {error}
          </p>
        )}
      </div>

      <div>
        <label htmlFor="login-email" className="mb-1 block text-sm font-medium">
          Email
        </label>
        <input
          id="login-email"
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

      <div>
        <label htmlFor="login-password" className="mb-1 block text-sm font-medium">
          Password
        </label>
        <input
          id="login-password"
          name="password"
          type="password"
          required
          autoComplete="current-password"
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
        {pending ? "Signing in…" : "Sign in"}
      </button>

      <p className="text-sm text-muted">
        New to Toke Cosmetics?{" "}
        <Link
          href={`/register?next=${encodeURIComponent(state.next ?? next)}`}
          className="underline hover:text-foreground"
        >
          Create an account
        </Link>
      </p>
      {/* No "Forgot password?" link until /forgot-password exists (Plan-15a item 7) — a
          visible link to a 404 is worse than no link. */}
    </form>
  );
}
