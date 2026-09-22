import type { Metadata } from "next";
import { NotificationSection } from "@/components/NotificationPanel";
import { Tabs } from "@/app/(shell)/careers/page";
import {
  addRecipientAction,
  markConfirmedAction,
  removeRecipientAction,
  resendConfirmationAction,
  testSendAction,
} from "@/app/(shell)/careers/notifications/actions";
import { ApiError } from "@/lib/api";
import { getAdminMeOrNull } from "@/lib/admin-me";
import { recipientsFor, type NotificationRecipient, type StaffOption } from "@/lib/notifications";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Application alerts" };

const PATH = "/careers/notifications";

/** Must match `apps/careers/emails.py::EVENT_APPLICATION_RECEIVED`. Hardcoded here and
 *  nowhere else in the admin: this screen is about ONE event, and reading the registry
 *  to find it would be a request whose only possible answer is this string. */
const EVENT_CODE = "careers.application_received";

/**
 * `/careers/notifications` — who gets emailed when somebody applies.
 *
 * ── THE SAME UI AS THE EMAIL NOTIFICATIONS SCREEN, ON PURPOSE ───────────────────────
 *
 * `NotificationSection` is rendered verbatim, with this screen's actions passed in. It
 * already solves everything that is fiddly about this list — the staff/external split,
 * the pending-confirmation state, the "resolves to nobody" warning for a deactivated
 * colleague, and the empty-list banner that is the whole point of the component. A
 * second implementation would have to re-derive all of it and would drift.
 *
 * What differs is behind the actions: they post to the careers-scoped endpoint, which
 * Owner AND Manager can reach and which can only ever touch this one event.
 *
 * ── WHY THE EVENT DESCRIPTION IS WRITTEN HERE ───────────────────────────────────────
 *
 * The general screen reads label and description from `/events/`, so a new backend event
 * needs no frontend deploy. That promise is about a LIST that grows; this page renders
 * one known event, and spending a request to be told its description — then having to
 * cope with the event having been removed from the registry — buys nothing. The words
 * are aimed at this screen's reader rather than at somebody scanning six events.
 */
export default async function CareersNotificationsPage() {
  await requireAdmin(PATH);

  const me = await getAdminMeOrNull();
  const scopes = new Set(me?.scopes ?? []);

  let recipients: NotificationRecipient[] = [];
  let staffOptions: StaffOption[] = [];
  let error: string | null = null;
  try {
    const [rows, staff] = await Promise.all([
      fetchWithAuthOrBounce<NotificationRecipient[]>("/admin/careers/notifications/", PATH),
      // The picker degrades rather than failing the page: without it you can still add
      // an email address, which is the more common case anyway.
      fetchWithAuthOrBounce<StaffOption[]>(
        "/admin/careers/notifications/staff-options/",
        PATH,
      ).catch(() => []),
    ]);
    recipients = Array.isArray(rows) ? rows : [];
    staffOptions = Array.isArray(staff) ? staff : [];
  } catch (e) {
    // `redirect()` throws, so a bare catch-all would swallow the session-renewal bounce.
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include changing who is emailed about applications."
        : "The notification list could not be loaded.";
  }

  return (
    <div>
      <h1 className="text-lg font-semibold tracking-tight">Careers</h1>
      <p className="mt-1 text-sm text-muted">
        Who hears about it when somebody applies through the careers page.
      </p>
      <Tabs
        active="notifications"
        canSeeApplications={scopes.has("careers.applications.manage")}
        canSeeNotifications
      />

      <div className="mt-6 max-w-3xl">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <>
            <NotificationSection
              event={{
                code: EVENT_CODE,
                label: "New job application",
                description:
                  "Sent the moment somebody applies. It names the role and the candidate " +
                  "and nothing else — their contact details and CV stay behind this login, " +
                  "because an address on this list may not have one.",
              }}
              recipients={recipientsFor(recipients, EVENT_CODE)}
              staffOptions={staffOptions}
              addAction={addRecipientAction}
              removeAction={removeRecipientAction}
              testAction={testSendAction}
              resendAction={resendConfirmationAction}
              markConfirmedAction={markConfirmedAction}
              // Vouching reaches every pending row for the address, including events this
              // screen cannot show — so it stays Owner-only here even though the rest of
              // the tab is Owner + Manager. The endpoint refuses regardless; this stops a
              // Manager being offered a button whose only outcome is a 403.
              canVouch={scopes.has("settings.manage")}
            />

            <p className="mt-4 text-xs leading-relaxed text-muted">
              An address with no staff account is emailed a confirmation link and receives
              nothing until somebody clicks it — that is how a mistyped address is caught,
              since otherwise it looks exactly like a working one.
              {scopes.has("settings.manage") ? (
                <>
                  {" "}
                  You can vouch for an address instead, which skips the click. Only the
                  Owner can: confirming an address confirms it for every alert it is on,
                  including ones this screen does not show.
                </>
              ) : (
                <>
                  {" "}
                  If a link never arrives, use Resend confirmation. Vouching for an address
                  without its click is the Owner&apos;s to do.
                </>
              )}
            </p>
          </>
        )}
      </div>
    </div>
  );
}
