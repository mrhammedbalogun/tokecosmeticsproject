"use client";

/**
 * One event's section: who receives it, the controls to change that, and the warning
 * when the answer is nobody.
 *
 * A CLIENT COMPONENT because every control uses `useActionState` to render its result
 * without a navigation. `initialState` on each is a test seam — it lets the rendered
 * states be asserted directly instead of by driving a Server Function through the DOM,
 * which vitest cannot do. Same shape as `InvitePanel`.
 *
 * NO CONFIRMATION DIALOG ON REMOVE. `window.confirm` blocks the extension's automation,
 * and the action is cheap to undo (add them again). The accessible name carries the
 * recipient so the wrong button is hard to press in the first place.
 *
 * THE EMPTY-LIST WARNING IS THE POINT OF THIS COMPONENT. The backend deliberately has no
 * silent fallback when an event has no recipients — a hidden "send it to the Owner
 * anyway" branch is exactly how the old `DEFAULT_FROM_EMAIL` bug went unnoticed for
 * months. This banner is the visible replacement for that safety net, so an event nobody
 * hears about says so on the screen instead of failing quietly in a Celery worker.
 */
import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import type { AddState, RowState } from "@/app/(shell)/notifications/actions";
import {
  labelFor,
  type NotificationEvent,
  type NotificationRecipient,
  type StaffOption,
} from "@/lib/notifications";

const INPUT =
  "mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent";

function Submit({
  label,
  pendingLabel,
  subtle = false,
  title,
  disabled = false,
}: {
  label: string;
  pendingLabel: string;
  subtle?: boolean;
  title?: string;
  disabled?: boolean;
}) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending || disabled}
      title={title}
      aria-label={title}
      className={
        subtle
          ? "rounded-md border border-line px-2.5 py-1 text-xs text-muted transition-colors hover:border-accent hover:text-fg disabled:opacity-60"
          : "rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
      }
    >
      {pending ? pendingLabel : label}
    </button>
  );
}

function RowForm({
  action,
  recipientId,
  label,
  pendingLabel,
  title,
  initialState = {},
}: {
  action: (prev: RowState, fd: FormData) => Promise<RowState>;
  recipientId: number;
  label: string;
  pendingLabel: string;
  title: string;
  initialState?: RowState;
}) {
  const [state, formAction] = useActionState<RowState, FormData>(action, initialState);
  return (
    <form action={formAction} className="inline">
      {/* The id rides in a hidden field rather than a closure — visible in the DOM,
          submitted by the browser, re-validated server-side. */}
      <input type="hidden" name="recipient_id" value={recipientId} />
      <Submit label={label} pendingLabel={pendingLabel} subtle title={title} />
      {state.error ? (
        <span role="alert" className="ml-2 text-xs text-danger">
          {state.error}
        </span>
      ) : null}
      {state.success ? (
        <span role="status" className="ml-2 text-xs text-accent">
          {state.success}
        </span>
      ) : null}
    </form>
  );
}

export function NotificationSection({
  event,
  recipients,
  staffOptions,
  addAction,
  removeAction,
  testAction,
  initialAddState = {},
}: {
  event: NotificationEvent;
  recipients: NotificationRecipient[];
  staffOptions: StaffOption[];
  addAction: (prev: AddState, fd: FormData) => Promise<AddState>;
  removeAction: (prev: RowState, fd: FormData) => Promise<RowState>;
  testAction: (prev: RowState, fd: FormData) => Promise<RowState>;
  initialAddState?: AddState;
}) {
  const [addState, addFormAction] = useActionState<AddState, FormData>(
    addAction,
    initialAddState,
  );

  // Staff already on this list are dropped from the picker. The backend refuses the
  // duplicate anyway ("That recipient is already on this list"), but offering a choice
  // whose only outcome is an error is a worse screen than not offering it.
  const alreadySubscribed = new Set(
    recipients.filter((r) => r.user !== null).map((r) => r.user),
  );
  const available = staffOptions.filter((option) => !alreadySubscribed.has(option.id));

  return (
    <section className="rounded-[var(--radius-card)] border border-line bg-surface p-4">
      <h2 className="text-sm font-semibold">{event.label}</h2>
      <p className="mt-1 text-xs text-muted">{event.description}</p>

      {recipients.length === 0 ? (
        <p
          role="alert"
          className="mt-3 rounded-md border border-warn/30 bg-warn/5 px-3 py-2 text-sm text-warn"
        >
          Nobody receives this. It will be sent to no one until you add a recipient below.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-line/60 border-y border-line/60">
          {recipients.map((row) => (
            <li
              key={row.id}
              className="flex flex-wrap items-center justify-between gap-2 py-2"
            >
              <span className="text-sm">
                {labelFor(row)}
                {row.is_external ? (
                  <span
                    className="ml-2 inline-block rounded bg-warn/10 px-1.5 py-0.5 text-[11px] font-medium text-warn"
                    title="No admin account. This address receives order emails with no login and no second factor behind it."
                  >
                    External
                  </span>
                ) : null}
                {/* A staff row whose account is deactivated or no longer staff. Shown
                    rather than hidden: silently dropping it is how somebody believes
                    they are still subscribed when they are not. */}
                {!row.is_external && !row.address ? (
                  <span className="ml-2 inline-block rounded bg-danger/10 px-1.5 py-0.5 text-[11px] font-medium text-danger">
                    Account inactive — receives nothing
                  </span>
                ) : null}
                {!row.is_external && row.address ? (
                  <span className="block text-xs text-muted">{row.address}</span>
                ) : null}
              </span>
              <span className="flex items-center gap-2">
                <RowForm
                  action={testAction}
                  recipientId={row.id}
                  label="Send test"
                  pendingLabel="Sending…"
                  title={`Send a test ${event.label} email to ${labelFor(row)}`}
                />
                <RowForm
                  action={removeAction}
                  recipientId={row.id}
                  label="Remove"
                  pendingLabel="Removing…"
                  title={`Stop emailing ${labelFor(row)} about ${event.label}`}
                />
              </span>
            </li>
          ))}
        </ul>
      )}

      {addState.error ? (
        <p
          role="alert"
          className="mt-3 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger"
        >
          {addState.error}
        </p>
      ) : null}
      {addState.success ? (
        <p
          role="status"
          className="mt-3 rounded-md border border-accent/30 bg-accent/5 px-3 py-2 text-sm"
        >
          {addState.success}
        </p>
      ) : null}

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <form action={addFormAction} className="rounded-md border border-line/60 p-3">
          <input type="hidden" name="event" value={event.code} />
          <input type="hidden" name="kind" value="staff" />
          <label
            className="block text-xs font-medium"
            htmlFor={`staff-${event.code}`}
          >
            Add a staff member
          </label>
          <select
            id={`staff-${event.code}`}
            name="user"
            className={INPUT}
            defaultValue=""
            disabled={available.length === 0}
          >
            <option value="" disabled>
              {available.length === 0 ? "Everyone is already on this list" : "Choose…"}
            </option>
            {available.map((option) => (
              <option key={option.id} value={option.id}>
                {option.name} ({option.email})
              </option>
            ))}
          </select>
          <div className="mt-2">
            {/* Disabled alongside the empty select. Leaving it live would offer a
                button whose only possible outcome is "Choose a staff member." */}
            <Submit
              label="Add"
              pendingLabel="Adding…"
              subtle
              disabled={available.length === 0}
            />
          </div>
        </form>

        <form action={addFormAction} className="rounded-md border border-line/60 p-3">
          <input type="hidden" name="event" value={event.code} />
          <input type="hidden" name="kind" value="external" />
          <label
            className="block text-xs font-medium"
            htmlFor={`email-${event.code}`}
          >
            Add an email address
          </label>
          <input
            id={`email-${event.code}`}
            name="email"
            type="email"
            autoComplete="off"
            placeholder="packing@example.com"
            className={INPUT}
          />
          <p className="mt-1 text-[11px] text-muted">
            For someone without an admin login. Send them a test afterwards — a mistyped
            address fails silently.
          </p>
          <div className="mt-2">
            <Submit label="Add" pendingLabel="Adding…" subtle />
          </div>
        </form>
      </div>
    </section>
  );
}

export function OrphanedRecipients({
  rows,
  removeAction,
}: {
  rows: NotificationRecipient[];
  removeAction: (prev: RowState, fd: FormData) => Promise<RowState>;
}) {
  if (rows.length === 0) return null;
  return (
    <section className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4">
      <h2 className="text-sm font-semibold text-warn">Recipients with no notification</h2>
      <p className="mt-1 text-xs text-muted">
        These rows point at a notification that no longer exists — usually because it was
        renamed. They receive nothing. Removing them is safe.
      </p>
      <ul className="mt-3 divide-y divide-line/60 border-y border-line/60">
        {rows.map((row) => (
          <li key={row.id} className="flex items-center justify-between gap-2 py-2">
            <span className="text-sm">
              {labelFor(row)}
              <span className="block text-xs text-muted">{row.event}</span>
            </span>
            <RowForm
              action={removeAction}
              recipientId={row.id}
              label="Remove"
              pendingLabel="Removing…"
              title={`Remove ${labelFor(row)} from ${row.event}`}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
