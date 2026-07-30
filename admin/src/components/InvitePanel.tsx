"use client";

/**
 * The two invite controls: the form that sends one, and the list that revokes one.
 *
 * CLIENT COMPONENTS because both use `useActionState` to render the action's result
 * without a navigation. `initialState` is a test seam — it lets the rendered states be
 * asserted directly instead of by driving a Server Function through the DOM, which
 * vitest cannot do.
 *
 * REVOKE IS A FORM, NOT AN `onClick` FETCH. It is a write, so it goes through the same
 * Server Function path as everything else, and the invite id rides in a hidden field
 * rather than a closure — which means it is visible in the DOM, submitted by the browser,
 * and re-validated server-side, all of which are properties a click handler would not
 * have.
 *
 * NO CONFIRMATION DIALOG. `window.confirm` blocks the extension's automation, and the
 * action is cheap to undo (invite again). The accessible name carries the address so the
 * wrong button is hard to press in the first place.
 */
import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { ROLES, isOutstanding, type StaffInvite } from "@/lib/staff";
import type { InviteState, RevokeState } from "@/app/(shell)/staff/actions";

const INPUT =
  "mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent";

function Submit({ label, pendingLabel }: { label: string; pendingLabel: string }) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
    >
      {pending ? pendingLabel : label}
    </button>
  );
}

export function InviteForm({
  action,
  initialState = {},
}: {
  action: (prev: InviteState, fd: FormData) => Promise<InviteState>;
  initialState?: InviteState;
}) {
  const [state, formAction] = useActionState<InviteState, FormData>(action, initialState);

  return (
    <form action={formAction} className="rounded-[var(--radius-card)] border border-line bg-surface p-4">
      <h2 className="text-sm font-semibold">Invite a staff member</h2>
      <p className="mt-1 text-xs text-muted">
        They receive a link that expires, and set their own password. Inviting somebody who
        already has a staff account is refused — change an existing member&rsquo;s role
        instead.
      </p>

      {state.error ? (
        <p
          role="alert"
          className="mt-3 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger"
        >
          {state.error}
        </p>
      ) : null}
      {state.success ? (
        <p
          role="status"
          className="mt-3 rounded-md border border-accent/30 bg-accent/5 px-3 py-2 text-sm"
        >
          {state.success}
        </p>
      ) : null}

      <div className="mt-3 grid gap-3 sm:grid-cols-[2fr_1fr_auto] sm:items-end">
        <div>
          <label className="block text-sm font-medium" htmlFor="invite-email">
            Email
          </label>
          <input
            id="invite-email"
            name="email"
            type="email"
            autoComplete="off"
            required
            className={INPUT}
          />
        </div>
        <div>
          <label className="block text-sm font-medium" htmlFor="invite-role">
            Role
          </label>
          <select id="invite-role" name="role" defaultValue="Support" className={INPUT}>
            {ROLES.map((role) => (
              <option key={role} value={role}>
                {role}
              </option>
            ))}
          </select>
        </div>
        <Submit label="Send invite" pendingLabel="Sending…" />
      </div>
    </form>
  );
}

function RevokeButton({ invite }: { invite: StaffInvite }) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      aria-label={`Revoke the invite for ${invite.email}`}
      className="rounded border border-line px-2 py-1 text-xs text-danger hover:border-danger disabled:opacity-60"
    >
      {pending ? "Revoking…" : "Revoke"}
    </button>
  );
}

export function InviteList({
  invites,
  revokeAction,
  initialState = {},
}: {
  invites: StaffInvite[];
  revokeAction: (prev: RevokeState, fd: FormData) => Promise<RevokeState>;
  initialState?: RevokeState;
}) {
  const [state, formAction] = useActionState<RevokeState, FormData>(revokeAction, initialState);
  // Filtered HERE rather than by asking the API for pending only: the endpoint has no
  // such filter, the list is a handful of rows, and `state` is the field that says which.
  const outstanding = invites.filter(isOutstanding);

  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-surface p-4">
      <h2 className="text-sm font-semibold">Outstanding invites</h2>
      <p className="mt-1 text-xs text-muted">
        Each of these is a live capability to create an administrator. Revoking is the kill
        switch for one sent to the wrong address.
      </p>

      {state.error ? (
        <p
          role="alert"
          className="mt-3 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger"
        >
          {state.error}
        </p>
      ) : null}

      {outstanding.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No outstanding invites.</p>
      ) : (
        <ul className="mt-3 divide-y divide-line/60">
          {outstanding.map((invite) => (
            <li key={invite.id} className="flex flex-wrap items-center gap-3 py-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm">{invite.email}</p>
                <p className="text-xs text-muted">
                  {invite.role} · expires {invite.expires_at.slice(0, 10)}
                  {invite.invited_by ? ` · invited by ${invite.invited_by}` : ""}
                </p>
              </div>
              <form action={formAction}>
                <input type="hidden" name="invite_id" value={invite.id} />
                <RevokeButton invite={invite} />
              </form>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
