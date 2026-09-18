"use client";
import Link from "next/link";
import { useHasSession } from "@/components/session/SessionProvider";

/**
 * `signedIn` is now an optional OVERRIDE, exactly as `WishlistLink`'s already was.
 *
 * Given, it wins — that is the dynamic header, which resolved the answer server-side and
 * renders the right control in the first byte of HTML, with no flicker. Omitted, the
 * session context decides, which is what a PRERENDERED page needs: its HTML is shared by
 * every visitor, so "Account" or "Sign in" cannot be a build-time decision.
 *
 * Unknown reads as signed OUT rather than blank. A prerendered page briefly showing
 * "Sign in" to a signed-in shopper self-corrects the moment `/api/shell` answers; a
 * blank gap in the header would not self-correct if that fetch ever failed, and would
 * shift the layout when it did land.
 */
export function AccountMenu({ signedIn }: { signedIn?: boolean } = {}) {
  const fromContext = useHasSession();
  return (signedIn ?? fromContext ?? false) ? (
    <Link href="/account" className="whitespace-nowrap text-sm hover:text-accent">Account</Link>
  ) : (
    <Link href="/login" className="whitespace-nowrap text-sm hover:text-accent">Sign in</Link>
  );
}
