"use client";

import { useFormStatus } from "react-dom";

function Button() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded border border-white/20 px-3 py-1.5 text-xs font-medium text-white/80 transition-colors hover:bg-shell-soft hover:text-white disabled:opacity-60"
    >
      {pending ? "Signing out…" : "Sign out"}
    </button>
  );
}

/** A form, not an onClick fetch: a Server Action gets Next's Origin/Host check for free and
 *  works without JavaScript, which is the right shape for the one control that ends a
 *  session. */
export function SignOutButton({ action }: { action: () => Promise<void> }) {
  return (
    <form action={action}>
      <Button />
    </form>
  );
}
