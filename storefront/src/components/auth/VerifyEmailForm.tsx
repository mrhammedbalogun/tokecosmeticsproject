"use client";

/**
 * The confirm button, plus whatever the attempt returned.
 *
 * A client component only so the result can replace the button without a reload. The
 * submission is a Server Function, so this still works with JavaScript off.
 */
import Link from "next/link";
import { useActionState } from "react";
import type { VerifyState } from "@/app/(auth)/verify-email/actions";

export function VerifyEmailForm({
  token,
  action,
}: {
  token: string;
  action: (state: VerifyState, formData: FormData) => Promise<VerifyState>;
}) {
  const [state, formAction, pending] = useActionState(action, {});

  if (state.verified) {
    return (
      <div>
        <p role="status" className="text-sm">
          Your email is confirmed — thank you.
        </p>
        {(state.ordersClaimed ?? 0) > 0 && (
          <p className="mt-2 text-sm text-muted">
            We also linked {state.ordersClaimed} previous{" "}
            {state.ordersClaimed === 1 ? "order" : "orders"} placed with this address to your
            account.
          </p>
        )}
        <Link
          href="/account"
          className="mt-6 inline-block rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong"
        >
          Go to my account
        </Link>
      </div>
    );
  }

  return (
    <form action={formAction} className="space-y-4">
      <input type="hidden" name="token" value={token} />

      <div aria-live="polite">
        {state.error && (
          <p role="alert" className="text-sm text-red-700">
            {state.error}
          </p>
        )}
      </div>

      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
      >
        {pending ? "Confirming…" : "Confirm my email"}
      </button>

      {state.error && (
        <p className="text-sm text-muted">
          Confirmation links expire 7 days after they are sent. If this one has expired,{" "}
          <Link href="/login" className="underline hover:text-foreground">
            sign in
          </Link>{" "}
          and we can send a new one.
        </p>
      )}
    </form>
  );
}
