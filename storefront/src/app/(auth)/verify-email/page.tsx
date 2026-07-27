import type { Metadata } from "next";
import { VerifyEmailForm } from "@/components/auth/VerifyEmailForm";
import { verifyEmailAction } from "./actions";
import { first } from "@/lib/search-params";

export const metadata: Metadata = {
  title: "Confirm your email",
  robots: { index: false, follow: false },
  // The token is in the URL, so no outbound request from this page may carry a Referer.
  referrer: "no-referrer",
};

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/**
 * Confirm an email address — the landing page for the link in the registration email
 * (`accounts/views.py` mails `${FRONTEND_URL}/verify-email?token=…`).
 *
 * THIS PAGE DOES NOT VERIFY ANYTHING. It renders a button that does.
 *
 * That is deliberate and is the only interesting decision here. Corporate mail scanners and
 * Outlook SafeLinks *fetch* every link in an email before the recipient ever clicks. If
 * confirmation happened as a side effect of rendering, the scanner would mark the address
 * verified and trigger `claim_legacy_orders` — so a machine, not the person, would satisfy
 * the one thing email verification exists to prove, and past orders would be linked to the
 * account with nobody having asked. Prefetches and "open in a new tab to check" behave the
 * same way. A GET that mutates is wrong independent of who issues it.
 *
 * (The token itself is a stateless signed token — `accounts/verification.py`, valid 7 days,
 * verified rather than consumed — so a scanner fetch would NOT lock the real user out, and
 * re-clicking is harmless. That makes this a correctness and consent problem rather than a
 * lockout one, which is still reason enough not to mutate on GET.)
 *
 * The backend agrees: `VerifyEmailView` is POST-only.
 */
export default async function VerifyEmailPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  // `first()` because `?token=a&token=b` arrives as an array.
  const token = first((await searchParams).token) ?? "";

  return (
    <div className="w-full">
      <h1 className="font-display text-3xl">Confirm your email</h1>

      {token ? (
        <>
          <p className="mt-2 text-sm text-muted">
            One tap and your account is active. Confirming also links any past orders placed
            with this address.
          </p>
          <div className="mt-6">
            <VerifyEmailForm token={token} action={verifyEmailAction} />
          </div>
        </>
      ) : (
        <p role="alert" className="mt-4 text-sm text-red-700">
          This link is incomplete — it has no confirmation token. Please open the link from
          your email again, or sign in and we can send a fresh one.
        </p>
      )}
    </div>
  );
}
