"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import type { PartnerLoginState } from "@/app/partner/login/actions";

function Submit() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="mt-5 w-full rounded-md bg-accent px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
    >
      {pending ? "Signing in…" : "Sign in"}
    </button>
  );
}

export function PartnerLoginForm({
  action,
}: {
  action: (prev: PartnerLoginState, formData: FormData) => Promise<PartnerLoginState>;
}) {
  const [state, formAction] = useActionState<PartnerLoginState, FormData>(action, {});

  return (
    <form action={formAction} noValidate>
      {state.error ? (
        <p
          role="alert"
          className="mb-4 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger"
        >
          {state.error}
        </p>
      ) : null}

      <label className="block text-sm font-medium" htmlFor="email">
        Email
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

      <Submit />

      <p className="mt-4 text-xs text-muted">
        Forgot your password? Contact Toke Cosmetics to have it reset.
      </p>
    </form>
  );
}
