"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { TurnstileWidget } from "@/components/TurnstileWidget";
import type { LoginState } from "@/app/login/actions";

function Submit() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="mt-5 w-full rounded-md bg-accent px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
    >
      {pending ? "Checking…" : "Continue"}
    </button>
  );
}

export function LoginForm({
  next,
  action,
}: {
  next: string;
  action: (prev: LoginState, formData: FormData) => Promise<LoginState>;
}) {
  const [state, formAction] = useActionState<LoginState, FormData>(action, { next });

  return (
    <form action={formAction} className="mt-6" noValidate>
      <input type="hidden" name="next" value={state.next ?? next} />

      {state.error ? (
        <p
          role="alert"
          className="mb-4 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger"
        >
          {state.error}
        </p>
      ) : null}

      <label className="block text-sm font-medium" htmlFor="email">
        Work email
      </label>
      <input
        id="email"
        name="email"
        type="email"
        autoComplete="username"
        required
        defaultValue={state.email ?? ""}
        className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
      />

      <label className="mt-4 block text-sm font-medium" htmlFor="password">
        Password
      </label>
      <input
        id="password"
        name="password"
        type="password"
        autoComplete="current-password"
        required
        className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
      />

      {/* resetSignal: Turnstile tokens are single-use, so a failed submit must fetch a
          fresh one or the retry is rejected as a duplicate. */}
      <TurnstileWidget resetSignal={state} />

      <Submit />

      <p className="mt-4 text-xs text-muted">
        You will be asked for a code from your authenticator app next.
      </p>
    </form>
  );
}
