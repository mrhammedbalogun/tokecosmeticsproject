/**
 * Shapes and grouping for the Email Notifications page. No fetching here.
 *
 * NOTE WHAT IS *NOT* IN THIS FILE: the event list. Unlike `staff.ts`, which keeps a local
 * copy of `ROLES` because the RBAC design changes roughly never, the event registry
 * (`backend/apps/notifications/events.py`) exists precisely to be added to. A copy here
 * would mean every new backend event needed a matching frontend deploy before anybody
 * could subscribe to it — which is the promise the registry was built to make. The page
 * reads it from `/admin/notification-recipients/events/` instead and renders whatever
 * comes back.
 */

/** One subscribable event, as the backend registry describes it. */
export interface NotificationEvent {
  code: string;
  label: string;
  description: string;
}

/** One row of the subscriber list. */
export interface NotificationRecipient {
  id: number;
  event: string;
  /** Staff account id, or null on a standalone-address row. */
  user: number | null;
  /** The typed address on a standalone row; "" on a staff row. */
  email: string;
  /**
   * What the row resolves to TODAY — "" when a staff account has been deactivated or
   * demoted out of staff. The page renders that case as a warning rather than dropping
   * the row, because a subscription that silently stops is the bug this whole feature
   * exists to end.
   */
  address: string;
  staff_name: string;
  is_external: boolean;
}

/** An option in the "add a staff member" picker. */
export interface StaffOption {
  id: number;
  email: string;
  name: string;
}

/**
 * Rows for one event, in a stable order: staff first, then external addresses, each
 * alphabetical.
 *
 * The grouping is deliberate rather than cosmetic. An external address — no account, no
 * second factor, receives order contents indefinitely — is the row worth a second look
 * before you leave the page, and a list interleaved by insertion order buries it among
 * colleagues. Sorting them into their own block is what makes "who are these three
 * strangers?" an answerable question at a glance.
 */
export function recipientsFor(
  rows: readonly NotificationRecipient[],
  event: string,
): NotificationRecipient[] {
  return rows
    .filter((row) => row.event === event)
    .sort((a, b) => {
      if (a.is_external !== b.is_external) return a.is_external ? 1 : -1;
      return labelFor(a).localeCompare(labelFor(b));
    });
}

/** What to call a row on screen. Falls back through the fields that may be blank. */
export function labelFor(row: NotificationRecipient): string {
  if (row.is_external) return row.email;
  return row.staff_name || row.address || row.email || `Staff #${row.user}`;
}

/**
 * Rows whose event is no longer in the registry.
 *
 * These are not hidden. The backend keeps a subscription when its event code leaves the
 * registry (a rename, a refactor) rather than cascading it away, so the honest thing is
 * to show the orphan and let the Owner delete it. Hiding it would leave a row in the
 * database that the only screen that manages rows claims does not exist.
 */
export function orphanedRecipients(
  rows: readonly NotificationRecipient[],
  events: readonly NotificationEvent[],
): NotificationRecipient[] {
  const known = new Set(events.map((e) => e.code));
  return rows.filter((row) => !known.has(row.event));
}
