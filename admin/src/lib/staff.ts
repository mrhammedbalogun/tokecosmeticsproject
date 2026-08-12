/**
 * Shapes and vocabulary for the staff page. No fetching here.
 *
 * `ROLES` is a COPY of `backend/apps/accounts/rbac.ROLES`, and the duplication is
 * deliberate rather than accidental: the dropdown has to render four options before any
 * request is made, and an endpoint that returns the role list would be a round trip to
 * learn a constant that changes when the RBAC design changes — i.e. never, without a
 * migration. What matters is that this copy is not a CONTROL: `StaffInviteCreateSerializer`
 * validates the submitted role against the real table, so a drift here produces a 400
 * rather than an invite in a role that does not exist.
 */
export const ROLES = ["Owner", "Manager", "Support", "Content"] as const;
export type Role = (typeof ROLES)[number];

export function isRole(value: string): value is Role {
  return (ROLES as readonly string[]).includes(value);
}

/** One row of `/admin/staff/` — an account that exists today. */
export interface StaffMember {
  id: number;
  email: string;
  name: string;
  roles: string[];
  is_active: boolean;
  is_superuser: boolean;
  totp_confirmed: boolean;
  /** Which method the account confirmed — "totp", "email", or null for the enrolment
   *  gap the roster exists to surface. Optional so a backend deployed before Plan-33
   *  still renders (the table falls back to `totp_confirmed`). */
  second_factor?: "totp" | "email" | null;
  last_login: string | null;
  date_joined: string;
}

/** One row of `/admin/staff/invites/` — a capability in flight. */
export interface StaffInvite {
  id: number;
  email: string;
  role: string;
  state: string;
  expires_at: string;
  invited_by: string | null;
  accepted_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

/** The invite states worth a row on the page. Accepted invites are history — the person
 *  is on the roster above, which is the better answer to "did they join". */
export function isOutstanding(invite: StaffInvite): boolean {
  return invite.state === "pending";
}

/**
 * What to call an account whose group list is empty.
 *
 * A superuser has every scope regardless of groups, so "No role" would be the most
 * misleading label on the page. A non-superuser with no group genuinely holds nothing,
 * and saying so is what prompts somebody to fix it.
 */
export function roleLabel(member: StaffMember): string {
  if (member.roles.length) return member.roles.join(", ");
  return member.is_superuser ? "Superuser (all scopes)" : "No role";
}
