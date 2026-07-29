import type { Metadata } from "next";
import { TotpPanel } from "@/components/TotpPanel";
import { StagingBadge } from "@/components/StagingBadge";
import { gatePage } from "@/lib/session";
import { DEFAULT_NEXT, first, safeNext } from "@/lib/next-param";
import { confirmAction, enrolAction, recoveryAction } from "./actions";

export const metadata: Metadata = {
  title: "Two-factor authentication",
  robots: { index: false, follow: false },
};

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/**
 * Step two of the ceremony. Reachable ONLY while the `admin_preauth` cookie is present —
 * `gatePage("totp", …)` sends a cookieless visitor to `/login` and a fully-signed-in one to
 * the dashboard, and purges the anomaly.
 *
 * `setup` and `recovery` are UI hints carried in the URL rather than in a fourth cookie.
 * Neither is a security decision: the backend refuses to re-enrol a confirmed account
 * (409) and refuses a code against a non-existent enrolment, so a hand-edited query string
 * changes which screen is drawn and nothing else.
 */
export default async function TotpPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const next = safeNext(first(params.next), DEFAULT_NEXT);
  const setup = first(params.setup) === "1";
  const recovery = first(params.recovery) === "1";

  await gatePage("totp", "/totp");

  return (
    <main className="flex min-h-full items-center justify-center px-6 py-16">
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold tracking-tight">Toke Admin</h1>
          <StagingBadge />
        </div>
        <p className="mt-1 text-sm text-muted">Staff sign-in. Step 2 of 2.</p>
        <div className="mt-6 rounded-[var(--radius-card)] border border-line bg-surface p-6 shadow-sm">
          <TotpPanel
            next={next}
            setup={setup}
            recovery={recovery}
            enrolAction={enrolAction}
            confirmAction={confirmAction}
            recoveryAction={recoveryAction}
          />
        </div>
      </div>
    </main>
  );
}
