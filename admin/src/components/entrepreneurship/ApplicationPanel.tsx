"use client";

/**
 * One student, in full: how to reach them, what they study, what they wrote, and the two
 * things a reviewer may change.
 *
 * ── THE CONTACT ROW LEADS, AND THAT IS A DOMAIN DECISION ────────────────────────────
 *
 * On the careers equivalent the CV leads, because hiring starts with reading. This
 * programme starts with a phone call — nobody is handed stock without a conversation
 * first — so the number, and specifically the WhatsApp link, is the first thing on the
 * screen and the largest.
 *
 * ── DELETE IS BEHIND A TYPED CONFIRMATION ───────────────────────────────────────────
 *
 * It destroys the record permanently and the API allows it only to the Owner. A
 * one-click confirm is not enough proportion for the only irreversible action on this
 * screen — so the reviewer types the student's name, which also makes it almost
 * impossible to delete the wrong person by muscle memory.
 */
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  deleteApplication,
  updateApplication,
} from "@/app/(shell)/entrepreneurship/actions";
import {
  APPLICATION_STATUSES,
  whatsappUrl,
  type ApplicationDetail,
  type ApplicationStatus,
} from "@/lib/entrepreneurship";

export function ApplicationPanel({
  application,
  canDelete,
}: {
  application: ApplicationDetail;
  canDelete: boolean;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [status, setStatus] = useState<ApplicationStatus>(application.status);
  const [notes, setNotes] = useState(application.staff_notes);
  const [message, setMessage] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [confirming, setConfirming] = useState(false);

  function save(patch: { status?: ApplicationStatus; staff_notes?: string }) {
    startTransition(async () => {
      const result = await updateApplication(application.id, patch);
      setMessage(result.message ?? null);
      setSaved(Boolean(result.savedAt));
      if (result.savedAt) router.refresh();
    });
  }

  return (
    <div className="space-y-6">
      {message && (
        <p className="rounded-[var(--radius-card)] border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          {message}
        </p>
      )}

      <section className="rounded-[var(--radius-card)] border border-line bg-surface p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">{application.full_name}</h2>
            <p className="mt-1 text-sm text-muted">
              {application.institution}
              {application.country_name && ` · ${application.country_name}`}
            </p>
            <p className="mt-0.5 text-xs text-muted">
              Applied{" "}
              {new Date(application.created_at).toLocaleString("en-NG", {
                dateStyle: "long",
                timeStyle: "short",
              })}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {application.submission_count > 1 && (
              <span className="rounded-full border border-warn/40 bg-warn/5 px-3 py-1 text-xs text-warn">
                Replaced their own application ({application.submission_count}{" "}
                submissions)
              </span>
            )}
            {application.is_resubmission && (
              <span className="rounded-full border border-warn/40 bg-warn/5 px-3 py-1 text-xs text-warn">
                They applied before — look for the earlier one
              </span>
            )}
          </div>
        </div>

        <dl className="mt-6 grid gap-4 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted">Phone</dt>
            <dd className="mt-1 flex flex-wrap items-center gap-3">
              {/* The stored E.164 is what both links are BUILT from; the prettified
                  national form is only ever the text. Same rule as the store cards. */}
              <a href={`tel:${application.phone}`} className="text-accent underline">
                {application.phone_display || application.phone}
              </a>
              <a
                href={whatsappUrl(application.phone)}
                target="_blank"
                rel="noreferrer"
                className="rounded-full border border-line px-3 py-1 text-xs text-muted hover:border-accent/40"
              >
                WhatsApp
              </a>
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted">Email</dt>
            <dd className="mt-1">
              <a href={`mailto:${application.email}`} className="text-accent underline">
                {application.email}
              </a>
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted">Course</dt>
            <dd className="mt-1">
              {application.course_of_study}
              {application.academic_level && (
                <span className="text-muted"> · {application.academic_level}</span>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted">
              Where they post
            </dt>
            <dd className="mt-1">
              {application.social_handle || (
                <span className="text-muted">Not given</span>
              )}
            </dd>
          </div>
        </dl>
      </section>

      {application.motivation && (
        <section className="rounded-[var(--radius-card)] border border-line bg-surface p-5 sm:p-6">
          <h3 className="text-sm font-semibold">Why they want to join</h3>
          {/* `whitespace-pre-wrap`, because this is PLAIN TEXT typed into a textarea by
              a member of the public — there is no markup to render and no reason to
              accept any. Their paragraph breaks are the only formatting there is. */}
          <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">
            {application.motivation}
          </p>
        </section>
      )}

      <section className="rounded-[var(--radius-card)] border border-line bg-surface p-5 sm:p-6">
        <h3 className="text-sm font-semibold">Where this stands</h3>
        <p className="mt-1 text-xs text-muted">
          Approving records the decision. It does not send anything to the student and it
          does not release any stock — both of those are still a conversation.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          {APPLICATION_STATUSES.map((option) => (
            <button
              key={option.value}
              type="button"
              disabled={pending}
              onClick={() => {
                setStatus(option.value);
                save({ status: option.value });
              }}
              className={[
                "rounded-full border px-3.5 py-1.5 text-sm disabled:opacity-60",
                status === option.value
                  ? "border-accent bg-accent text-white"
                  : "border-line hover:border-accent/40",
              ].join(" ")}
            >
              {option.label}
            </button>
          ))}
        </div>
        {application.reviewed_at && (
          <p className="mt-3 text-xs text-muted">
            Last moved by {application.reviewed_by_name || "a colleague"} on{" "}
            {new Date(application.reviewed_at).toLocaleDateString("en-NG", {
              dateStyle: "long",
            })}
            .
          </p>
        )}

        <label className="mt-6 block">
          <span className="text-sm font-medium">Notes</span>
          <span className="mt-0.5 block text-xs text-muted">
            For the team. The student never sees these.
          </span>
          <textarea
            rows={5}
            value={notes}
            onChange={(e) => {
              setNotes(e.target.value);
              setSaved(false);
            }}
            className="mt-2 w-full rounded-[var(--radius-card)] border border-line bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/30"
          />
        </label>
        <div className="mt-2 flex items-center gap-3">
          <button
            type="button"
            disabled={pending}
            onClick={() => save({ staff_notes: notes })}
            className="rounded-[var(--radius-card)] border border-line px-4 py-2 text-sm disabled:opacity-60"
          >
            {pending ? "Saving…" : "Save notes"}
          </button>
          {saved && <span className="text-xs text-ok">Saved.</span>}
        </div>
      </section>

      {canDelete && (
        <section className="rounded-[var(--radius-card)] border border-danger/30 bg-danger/5 p-5 sm:p-6">
          <h3 className="text-sm font-semibold text-danger">Delete this application</h3>
          <p className="mt-1 text-sm text-muted">
            Removes the record permanently. There is no undo. This is what to use when
            somebody asks us to delete their details.
          </p>
          {confirming ? (
            <div className="mt-4 space-y-3">
              <label className="block text-sm">
                Type <strong>{application.full_name}</strong> to confirm
                <input
                  value={confirmText}
                  onChange={(e) => setConfirmText(e.target.value)}
                  className="mt-1.5 w-full max-w-sm rounded-[var(--radius-card)] border border-line bg-surface px-3 py-2 text-sm"
                />
              </label>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={pending || confirmText.trim() !== application.full_name}
                  onClick={() =>
                    startTransition(async () => {
                      const result = await deleteApplication(application.id);
                      if (result.message) {
                        setMessage(result.message);
                        return;
                      }
                      router.replace("/entrepreneurship");
                      router.refresh();
                    })
                  }
                  className="rounded-[var(--radius-card)] bg-danger px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
                >
                  Delete permanently
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setConfirming(false);
                    setConfirmText("");
                  }}
                  className="rounded-[var(--radius-card)] border border-line px-4 py-2 text-sm"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className="mt-4 rounded-[var(--radius-card)] border border-danger/40 px-4 py-2 text-sm text-danger"
            >
              Delete application
            </button>
          )}
        </section>
      )}
    </div>
  );
}
