"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { TurnstileWidget } from "@/components/TurnstileWidget";
import type { AcceptInviteState } from "@/app/accept-invite/actions";

function Submit() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="mt-5 w-full rounded-md bg-accent px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
    >
      {pending ? "Setting up…" : "Create my account"}
    </button>
  );
}

const INPUT =
  "mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent";

export function AcceptInviteForm({
  token,
  action,
}: {
  token: string;
  action: (prev: AcceptInviteState, fd: FormData) => Promise<AcceptInviteState>;
}) {
  const [state, formAction] = useActionState<AcceptInviteState, FormData>(action, {});

  return (
    <form action={formAction} className="mt-6" noValidate>
      {/* The invite token rides in a hidden field rather than being re-read from the URL
          by the action: a Server Action does not see the page's query string. */}
      <input type="hidden" name="token" value={token} />

      {state.error ? (
        <p
          role="alert"
          className="mb-4 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger"
        >
          {state.error}
        </p>
      ) : null}

      <label className="block text-sm font-medium" htmlFor="password">
        Choose a password
      </label>
      <input
        id="password"
        name="password"
        type="password"
        autoComplete="new-password"
        required
        className={INPUT}
      />

      <label className="mt-4 block text-sm font-medium" htmlFor="password_confirm">
        Confirm password
      </label>
      <input
        id="password_confirm"
        name="password_confirm"
        type="password"
        autoComplete="new-password"
        required
        className={INPUT}
      />

      <TurnstileWidget resetSignal={state} />
      <Submit />

      <p className="mt-4 text-xs text-muted">
        You will set up an authenticator app next. Every staff account needs one.
      </p>
    </form>
  );
}
