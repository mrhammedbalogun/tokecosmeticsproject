import type { Metadata } from "next";
import {
  NotificationSection,
  OrphanedRecipients,
} from "@/components/NotificationPanel";
import { ApiError } from "@/lib/api";
import {
  orphanedRecipients,
  recipientsFor,
  type NotificationEvent,
  type NotificationRecipient,
  type StaffOption,
} from "@/lib/notifications";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";
import {
  addRecipientAction,
  markConfirmedAction,
  removeRecipientAction,
  resendConfirmationAction,
  testSendAction,
} from "./actions";

export const metadata: Metadata = { title: "Email Notifications" };

const PATH = "/notifications";
const BASE = "/admin/notification-recipients/";

/**
 * `/notifications` — who is emailed when the shop needs a human.
 *
 * WHY A TOP-LEVEL NAV ITEM AND NOT A CARD ON `/settings`. It is Owner-only, which is an
 * argument for the Settings door — but `Staff` (nav.ts) is Owner-only and top-level
 * already, so the precedent for an Owner-only item exists and this is the same kind of
 * thing: a list of people and what reaches them. It is also the screen somebody opens
 * when an alert did not arrive, which is a moment for one click rather than two.
 *
 * THE EVENT LIST COMES FROM THE BACKEND, not a constant in this app. That is the whole
 * bargain of the registry in `backend/apps/notifications/events.py`: adding an event is a
 * backend-only change, and this page grows a section for it with no frontend deploy. A
 * copy in TypeScript would quietly break that on the first new event.
 *
 * ALL THREE FETCHES USE `fetchWithAuthOrBounce`, not `fetchWithAuth`: this is a Server
 * Component and cannot persist a rotated refresh token. They are settled with
 * `allSettled` rather than `all` so one failure does not discard the other two — and a
 * rejected promise here may be a `redirect()`, which works by throwing, so anything that
 * is not an `ApiError` is re-thrown rather than rendered. Same contract as `/staff`.
 */
export default async function NotificationsPage() {
  await requireAdmin(PATH);

  const [eventsResult, rowsResult, staffResult] = await Promise.allSettled([
    fetchWithAuthOrBounce<NotificationEvent[]>(`${BASE}events/`, PATH),
    fetchWithAuthOrBounce<NotificationRecipient[]>(BASE, PATH),
    fetchWithAuthOrBounce<StaffOption[]>(`${BASE}staff-options/`, PATH),
  ]);

  for (const result of [eventsResult, rowsResult, staffResult]) {
    if (result.status === "rejected" && !(result.reason instanceof ApiError)) {
      throw result.reason;
    }
  }

  const denied = [eventsResult, rowsResult, staffResult].some(
    (r) => r.status === "rejected" && (r.reason as ApiError).status === 403,
  );

  if (denied) {
    return (
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Email Notifications</h1>
        <p className="mt-6 rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
          Only the Owner can change who gets emailed.
        </p>
      </div>
    );
  }

  const events = eventsResult.status === "fulfilled" ? eventsResult.value : null;
  // The recipient list and the staff picker degrade independently. An empty picker still
  // leaves the email form usable, which is the half that matters when somebody is trying
  // to get an alert flowing again.
  const rows = rowsResult.status === "fulfilled" ? rowsResult.value : null;
  const staffOptions = staffResult.status === "fulfilled" ? staffResult.value : [];

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">Email Notifications</h1>
      <p className="mt-1 text-sm text-muted">
        Who gets emailed when something happens in the shop. Staff members and plain email
        addresses both work — an address needs no admin account.
      </p>

      {!events || !rows ? (
        <p className="mt-6 rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
          This page could not be loaded.
        </p>
      ) : (
        <div className="mt-6 space-y-4">
          {events.map((event) => (
            <NotificationSection
              key={event.code}
              event={event}
              recipients={recipientsFor(rows, event.code)}
              staffOptions={staffOptions}
              addAction={addRecipientAction}
              removeAction={removeRecipientAction}
              testAction={testSendAction}
              resendAction={resendConfirmationAction}
              markConfirmedAction={markConfirmedAction}
            />
          ))}
          <OrphanedRecipients
            rows={orphanedRecipients(rows, events)}
            removeAction={removeRecipientAction}
          />
          <p className="text-xs text-muted">
            Emails are sent one per recipient, so nobody sees who else is on a list.
            Removing a staff account from the admin stops their notifications
            automatically. An email address you add is sent a confirmation link first and
            receives nothing until someone there clicks it — which is what catches a
            mistyped address, since a wrong one otherwise just fails in silence. If you
            are certain an address is right, “Mark confirmed” skips the click. Either
            way, an address confirms once: adding it to other notifications later needs
            no new confirmation.
          </p>
        </div>
      )}
    </div>
  );
}
