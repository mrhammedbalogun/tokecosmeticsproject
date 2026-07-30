import type { Metadata } from "next";
import { AcceptInviteForm } from "@/components/AcceptInviteForm";
import { StagingBadge } from "@/components/StagingBadge";
import { gatePage } from "@/lib/session";
import { first } from "@/lib/next-param";
import { acceptInviteAction } from "./actions";

export const metadata: Metadata = {
  title: "Accept your invite",
  robots: { index: false, follow: false },
};

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/**
 * `/accept-invite?token=…` — on the gate's PUBLIC allowlist.
 *
 * It has to be public: the invitee has no session, and the capability they hold is the
 * token in the link. `gatePage("public", …)` therefore allows every cookie state through —
 * with one exception it does not get to opt out of, the anomaly, which purges. That
 * ordering lives in `decideAuth` rather than here precisely so no route class can be
 * exempted from failing closed by an edit to a page file.
 *
 * The token is NOT validated here. Doing so would mean an unauthenticated GET that tells a
 * caller whether a token is real, which is exactly the oracle the backend's uniform
 * "unknown / revoked / already used" message exists to deny. The first and only judgment
 * is made by Django, on submit.
 */
export default async function AcceptInvitePage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const token = first((await searchParams).token) ?? "";

  await gatePage("public", "/accept-invite");

  return (
    <main className="flex min-h-full items-center justify-center px-6 py-16">
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold tracking-tight">Toke Admin</h1>
          <StagingBadge />
        </div>
        <p className="mt-1 text-sm text-muted">
          {token
            ? "You have been invited to the Toke Cosmetics admin."
            : "This invite link is incomplete."}
        </p>
        <div className="mt-6 rounded-[var(--radius-card)] border border-line bg-surface p-6 shadow-sm">
          {token ? (
            <AcceptInviteForm token={token} action={acceptInviteAction} />
          ) : (
            <p className="text-sm text-muted">
              Open the link from your invitation email exactly as it was sent — the address
              needs the token that came with it. If it has expired, ask for a new invite.
            </p>
          )}
        </div>
      </div>
    </main>
  );
}
