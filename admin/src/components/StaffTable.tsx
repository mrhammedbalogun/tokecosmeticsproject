/**
 * The roster: who holds an administrator account today.
 *
 * A SERVER COMPONENT — nothing here is interactive. Deactivating a staff member is not a
 * button on this page and that is deliberate for now: the backend has no deactivate
 * endpoint (Plan-16 built invite and revoke, which govern accounts that do not exist
 * yet), so a control here would either be decorative or would need an endpoint nobody
 * has reviewed. The runbook's `manage.py` path remains the way, and Plan-18's customer
 * work is where an account-state endpoint belongs.
 *
 * THE TOTP COLUMN IS THE REASON THIS TABLE EARNS ITS PLACE. Everything else on it is
 * knowable from the invite list; "invited three weeks ago, never finished enrolling" is
 * not, and it describes an account that can pass the password door and stop.
 */
import { roleLabel, type StaffMember } from "@/lib/staff";

function when(value: string | null): string {
  if (!value) return "Never";
  // The raw ISO date, trimmed to the day. A locale format rendered on the server and
  // re-rendered in the browser is a hydration mismatch waiting to happen.
  return value.slice(0, 10);
}

export function StaffTable({ members }: { members: StaffMember[] }) {
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
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
