import type { Metadata } from "next";
import { InviteForm, InviteList } from "@/components/InvitePanel";
import { StaffTable } from "@/components/StaffTable";
import { ApiError } from "@/lib/api";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";
import type { StaffInvite, StaffMember } from "@/lib/staff";
import { inviteAction, revokeAction } from "./actions";

export const metadata: Metadata = { title: "Staff" };

const PATH = "/staff";

interface Paged<T> {
  results: T[];
}

/**
 * `/staff` — the roster, the outstanding invites, and the form that adds one.
 *
 * BOTH FETCHES USE `fetchWithAuthOrBounce`, not `fetchWithAuth`: this is a Server
 * Component and cannot persist a rotated refresh token. The writing fetcher would
 * blacklist the old one with nowhere to put the new — a silently ended session.
 *
 * THEY RUN CONCURRENTLY but are settled with `allSettled`, not `all`. The two calls carry
 * the same scope and will normally succeed or fail together, but `all` rejects on the
 * first failure and would discard a roster that arrived fine because the invite list
 * happened to error. Each panel renders its own answer.
 *
 * ONE SUBTLETY WORTH STATING: a rejected promise here may be a `redirect()`, which works
 * by throwing. `allSettled` captures it rather than letting it propagate, so the bounce
 * is re-thrown explicitly below — without that, a staff member with a merely-stale token
 * would see two error panels instead of being renewed.
 */
export default async function StaffPage() {
  await requireAdmin(PATH);

  const [rosterResult, invitesResult] = await Promise.allSettled([
    fetchWithAuthOrBounce<Paged<StaffMember>>("/admin/staff/", PATH),
    fetchWithAuthOrBounce<StaffInvite[]>("/admin/staff/invites/", PATH),
  ]);

  for (const result of [rosterResult, invitesResult]) {
    // Anything that is not an ApiError is not ours to render — including NEXT_REDIRECT,
    // which is how renewal and the login bounce both travel.
    if (result.status === "rejected" && !(result.reason instanceof ApiError)) {
      throw result.reason;
    }
  }

  const members = rosterResult.status === "fulfilled" ? rosterResult.value.results : null;
  // The invite list has `pagination_class = None` — it comes back as a bare array, not a
  // paged envelope. Handled defensively so a future decision to paginate it degrades to
  // an empty list rather than a crash.
  const invites =
    invitesResult.status === "fulfilled"
      ? Array.isArray(invitesResult.value)
        ? invitesResult.value
        : ((invitesResult.value as unknown as Paged<StaffInvite>).results ?? [])
      : null;

  const denied =
    (rosterResult.status === "rejected" && (rosterResult.reason as ApiError).status === 403) ||
    (invitesResult.status === "rejected" && (invitesResult.reason as ApiError).status === 403);

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">Staff</h1>
      <p className="mt-1 text-sm text-muted">
        Who can sign in to this admin, and the invites that have not been used yet.
      </p>

      {denied ? (
        <p className="mt-6 rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
          Only the Owner can manage staff.
        </p>
      ) : (
        <div className="mt-6 space-y-6">
          {members ? (
            <StaffTable members={members} />
          ) : (
            <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
              The staff list could not be loaded.
            </p>
          )}

          <InviteForm action={inviteAction} />

          {invites ? (
            <InviteList invites={invites} revokeAction={revokeAction} />
          ) : (
            <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
              The invite list could not be loaded.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
