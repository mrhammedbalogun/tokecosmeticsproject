"use client";

/**
 * One candidate, in full: contact details, cover letter, CV, and the two things a
 * reviewer may change.
 *
 * ── THE CV IS FETCHED THROUGH A SERVER ACTION, NOT LINKED ───────────────────────────
 *
 * There is no href to put on a button here. The admin's access token is an httpOnly
 * cookie the browser cannot read, and the API answers with a PRESIGNED S3 URL that lives
 * sixty seconds — so the flow is: click, ask the server, open what comes back. That is
 * also why neither button is a plain `<a>`: a link would be stale before it was clicked
 * twice, and a stale CV link reads as "the file is gone".
 *
 * ── DELETE IS BEHIND A TYPED CONFIRMATION ───────────────────────────────────────────
 *
 * It destroys the row AND the CV, permanently, and the API allows it only to the Owner.
 * A one-click confirm is not enough proportion for the only irreversible action on this
 * screen — so the reviewer types the candidate's name. That also makes it almost
 * impossible to delete the wrong person by muscle memory.
 */
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  deleteApplication,
  resumeLink,
  updateApplication,
} from "@/app/(shell)/careers/actions";
import {
  APPLICATION_STATUSES,
  formatBytes,
  whatsappUrl,
  type ApplicationDetail,
  type ApplicationStatus,
} from "@/lib/careers";

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

  function openResume(disposition: "inline" | "attachment") {
    startTransition(async () => {
      const result = await resumeLink(application.id, disposition);
      if (result.message || !result.url) {
        setMessage(result.message ?? "That CV could not be opened.");
        return;
      }
      setMessage(null);
      // `noopener` on every window we open onto a URL we did not author. The CV is a
      // file a member of the public uploaded; it renders on the S3 host, never ours, but
      // handing it a `window.opener` back into the admin would be careless anyway.
      window.open(result.url, "_blank", "noopener,noreferrer");
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
              Applied for <span className="text-foreground">{application.job_title}</span>
              {application.location_label && ` · ${application.location_label}`}
            </p>
            <p className="mt-0.5 text-xs text-muted">
              {new Date(application.created_at).toLocaleString("en-NG", {
                dateStyle: "long",
                timeStyle: "short",
              })}
            </p>
          </div>
          {application.submission_count > 1 && (
            <span className="rounded-full border border-warn/40 bg-warn/5 px-3 py-1 text-xs text-warn">
              Replaced their own application ({application.submission_count} submissions)
            </span>
          )}
          {application.is_resubmission && (
            <span className="rounded-full border border-warn/40 bg-warn/5 px-3 py-1 text-xs text-warn">
              They applied to this role before — look for the earlier one
            </span>
          )}
        </div>

        <dl className="mt-6 grid gap-4 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted">Email</dt>
            <dd className="mt-1">
              <a href={`mailto:${application.email}`} className="text-accent underline">
                {application.email}
              </a>
            </dd>
          </div>
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
                className="text-xs text-muted underline"
              >
                WhatsApp
              </a>
            </dd>
          </div>
        </dl>
      </section>

      <section className="rounded-[var(--radius-card)] border border-line bg-surface p-5 sm:p-6">
        <h3 className="text-sm font-semibold">CV</h3>
        {application.resume_original_name ? (
          <>
            <p className="mt-1 text-sm text-muted">
              {application.resume_original_name}
              {application.resume_size ? ` · ${formatBytes(application.resume_size)}` : ""}
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={pending}
                onClick={() => openResume("inline")}
                className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
              >
                View CV
              </button>
              <button
                type="button"
                disabled={pending}
                onClick={() => openResume("attachment")}
                className="rounded-[var(--radius-card)] border border-line px-4 py-2 text-sm disabled:opacity-60"
              >
                Download CV
              </button>
            </div>
            <p className="mt-3 text-xs text-muted">
              The link is good for one minute and is not shareable. Opening a CV is
              recorded in the audit log.
            </p>
          </>
        ) : (
          <p className="mt-1 text-sm text-muted">No CV on this application.</p>
        )}
      </section>

      {application.cover_letter && (
        <section className="rounded-[var(--radius-card)] border border-line bg-surface p-5 sm:p-6">
          <h3 className="text-sm font-semibold">Cover letter</h3>
          {/* `whitespace-pre-wrap`, because this is PLAIN TEXT typed into a textarea by
              a member of the public — there is no markup to render and no reason to
              accept any. Their paragraph breaks are the only formatting there is. */}
          <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">
            {application.cover_letter}
          </p>
        </section>
      )}

      <section className="rounded-[var(--radius-card)] border border-line bg-surface p-5 sm:p-6">
        <h3 className="text-sm font-semibold">Where this stands</h3>
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
            For the team. The candidate never sees these.
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
            Removes the record and permanently deletes their CV. There is no undo. This is
            what to use when somebody asks us to delete their data.
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
                      router.replace("/careers/applications");
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
