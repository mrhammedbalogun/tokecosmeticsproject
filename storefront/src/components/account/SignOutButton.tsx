"use client";

/**
 * Signs out via the auth BFF (which blacklists the refresh token best-effort and
 * clears the cookies), then `router.refresh()` BEFORE navigating — without it the
 * client router cache can serve stale signed-in /account HTML on Back
 * (storefront/AGENTS.md gotcha list).
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

export function SignOutButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function signOut() {
    setBusy(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch {
      // Cookies may already be gone; landing on the homepage signed-out is still
      // the right outcome, so fall through.
    }
    router.refresh();
    router.push("/");
  }

  return (
    <button
      type="button"
      onClick={signOut}
      disabled={busy}
      className="text-sm text-muted underline hover:text-foreground disabled:opacity-60"
    >
      {busy ? "Signing out…" : "Sign out"}
    </button>
  );
}
