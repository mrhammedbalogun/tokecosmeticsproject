/**
 * The roster: who holds an administrator account today.
 *
 * A SERVER COMPONENT; the one interactive control is `RemoveStaffButton`, a client
 * child injected with the Server Function (the same split as InviteList and revoke).
 * Removal shipped 2026-08-20 — `POST /admin/staff/<pk>/remove/` deactivates, de-roles
 * and signs the member out everywhere; the button never appears on Owner rows,
 * superusers, or the signed-in account, and the API refuses those anyway.
 *
 * THE TOTP COLUMN IS THE REASON THIS TABLE EARNS ITS PLACE. Everything else on it is
 * knowable from the invite list; "invited three weeks ago, never finished enrolling" is
 * not, and it describes an account that can pass the password door and stop.
 */
import { RemoveStaffButton } from "@/components/RemoveStaffButton";
import { roleLabel, type StaffMember } from "@/lib/staff";

function when(value: string | null): string {
  if (!value) return "Never";
  // The raw ISO date, trimmed to the day. A locale format rendered on the server and
  // re-rendered in the browser is a hydration mismatch waiting to happen.
  return value.slice(0, 10);
}

export function StaffTable({
  members,
  removeAction,
  selfEmail,
}: {
  members: StaffMember[];
  /** The Server Function behind the Remove buttons; absent = no buttons at all. */
  removeAction?: (memberId: number) => Promise<{ error?: string }>;
  /** The signed-in account, so its own row never offers to remove itself. */
  selfEmail?: string;
}) {
  // Owners (and superusers, who are Owners in effect — `scopes_for_user` short-circuits
  // them to every scope) are not removable through the admin; the API refuses them too.
  const removable = (member: StaffMember) =>
    !member.roles.includes("Owner") && !member.is_superuser && member.email !== selfEmail;

  if (members.length === 0) {
    // Unreachable in practice — somebody is reading this page, and they are staff — but
    // an empty table with no explanation is worse than a sentence.
    return (
      <p className="rounded-[var(--radius-card)] border border-line bg-surface p-6 text-sm text-muted">
        No staff accounts.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line bg-surface">
      <table className="w-full min-w-[44rem] text-left text-sm">
        <thead className="border-b border-line text-xs uppercase tracking-wide text-muted">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Name</th>
            <th scope="col" className="px-3 py-2 font-medium">Role</th>
            <th scope="col" className="px-3 py-2 font-medium">Second factor</th>
            <th scope="col" className="px-3 py-2 font-medium">Last sign-in</th>
            <th scope="col" className="px-3 py-2 font-medium">Joined</th>
            {removeAction && (
              <th scope="col" className="px-3 py-2 font-medium">
                <span className="sr-only">Remove</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {members.map((member) => (
            <tr key={member.id} className="border-b border-line/60 last:border-0">
              <td className="px-3 py-2">
                <span className="font-medium">{member.name || "—"}</span>
                <span className="block text-xs text-muted">{member.email}</span>
                {!member.is_active ? (
                  <span className="mt-1 inline-block rounded bg-warn/10 px-1.5 py-0.5 text-[11px] font-medium text-warn">
                    Deactivated
                  </span>
                ) : null}
              </td>
              <td className="px-3 py-2">{roleLabel(member)}</td>
              <td className="px-3 py-2">
                {member.second_factor === "totp" || member.totp_confirmed ? (
                  <span className="text-xs text-muted">Authenticator</span>
                ) : member.second_factor === "email" ? (
                  <span className="text-xs text-muted">Email codes</span>
                ) : (
                  <span className="rounded bg-warn/10 px-1.5 py-0.5 text-[11px] font-medium text-warn">
                    Not enrolled
                  </span>
                )}
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-xs text-muted">
                {when(member.last_login)}
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-xs text-muted">
                {when(member.date_joined)}
              </td>
              {removeAction && (
                <td className="px-3 py-2 text-right">
                  {removable(member) && (
                    <RemoveStaffButton
                      memberId={member.id}
                      email={member.email}
                      action={removeAction}
                    />
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
