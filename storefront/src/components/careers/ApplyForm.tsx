"use client";

/**
 * The application form. The only public write in this app that carries a file.
 *
 * ── THREE STEPS, ONE BUTTON ─────────────────────────────────────────────────────────
 *
 * Submitting does: mint an upload ticket (Turnstile is checked there), upload the CV
 * straight to S3, then POST the fields with the ticket key. The applicant sees one
 * button and a progress bar. `lib/careers.ts` explains why the bytes bypass our own
 * server; this file's job is to make that invisible.
 *
 * ── STATE IS DELIBERATELY NOT `useActionState` ──────────────────────────────────────
 *
 * Every other form in this app is a Server Function form. This one cannot be: a Server
 * Action caps its request body at 1MB, well under a 5MB CV, and the upload needs real
 * progress events, which only XHR gives. So it is a plain controlled form with its own
 * submit state — and, because of that, `required`/`type=email` stay on the inputs so the
 * browser's own validation still runs first.
 *
 * ── WHAT HAPPENS ON A FAILED SUBMIT ─────────────────────────────────────────────────
 *
 * The uploaded key is KEPT. If the phone number was malformed, or the role closed, or
 * the connection dropped at the last step, re-submitting does not re-upload the file —
 * which on a Nigerian mobile connection is the difference between one thirty-second wait
 * and two. The key is only cleared when the file itself changes.
 *
 * A Turnstile token, by contrast, is single-use: `resetSignal` is bumped on every
 * failure so the widget mints a fresh one, or the second attempt fails as a duplicate.
 */
import { useId, useRef, useState } from "react";
import { TurnstileWidget, turnstileToken } from "@/components/auth/TurnstileWidget";
import { PhoneField } from "@/components/ui/PhoneField";
import {
  ApplyError,
  MAX_RESUME_BYTES,
  RESUME_ACCEPT,
  resumeProblem,
  submitApplication,
  uploadResume,
  type Job,
} from "@/lib/careers";

const inputClass =
  "w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2.5 text-sm " +
  "focus:outline-none focus:ring-2 focus:ring-accent/40 disabled:opacity-60";

const COVER_LETTER_MAX = 5000;

type Phase = "idle" | "uploading" | "submitting" | "done";

export function ApplyForm({ job }: { job: Job }) {
  const formId = useId();
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  // Bumped on every failure: it is what makes Turnstile hand out a fresh single-use
  // token, and what re-announces the error to a screen reader on a repeat failure.
  const [attempt, setAttempt] = useState(0);

  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [coverLetter, setCoverLetter] = useState("");
  // Survives a failed submit so a retry does not re-upload. Cleared when the file does.
  const uploadedKey = useRef<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const busy = phase === "uploading" || phase === "submitting";

  function chooseFile(next: File | null) {
    uploadedKey.current = null;
    setProgress(0);
    if (!next) {
      setFile(null);
      setFileError(null);
      return;
    }
    const problem = resumeProblem(next);
    setFile(problem ? null : next);
    setFileError(problem);
    if (problem && fileInput.current) fileInput.current.value = "";
  }

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;

    const form = event.currentTarget;
    const data = new FormData(form);

    if (!file) {
      setFileError("Attach your CV to apply.");
      setMessage("Please check the highlighted fields.");
      setAttempt((n) => n + 1);
      return;
    }

    setMessage(null);
    setFieldErrors({});

    try {
      if (!uploadedKey.current) {
        setPhase("uploading");
        setProgress(0);
        uploadedKey.current = await uploadResume(file, {
          turnstileToken: turnstileToken(),
          onProgress: setProgress,
        });
      }

      setPhase("submitting");
      await submitApplication(job.slug, {
        full_name: String(data.get("full_name") ?? "").trim(),
        email: String(data.get("email") ?? "").trim(),
        // PhoneField submits E.164 through a hidden input; the visible one carries no
        // name, so this is always the diallable form or "".
        phone: String(data.get("phone") ?? "").trim(),
        cover_letter: coverLetter.trim(),
        location: data.get("location") ? Number(data.get("location")) : null,
        upload_key: uploadedKey.current,
        resume_filename: file.name,
        website: String(data.get("website") ?? ""),
        turnstile_token: turnstileToken(),
      });
      setPhase("done");
    } catch (error) {
      setPhase("idle");
      setAttempt((n) => n + 1);
      if (error instanceof ApplyError) {
        setMessage(error.message);
        setFieldErrors(error.fieldErrors);
        // A rejected FILE is the one failure that must invalidate the stored key —
        // otherwise every retry re-sends the same bytes the backend already refused.
        if (error.fieldErrors.resume) {
          uploadedKey.current = null;
          setFileError(error.fieldErrors.resume);
          setFile(null);
          if (fileInput.current) fileInput.current.value = "";
        }
      } else {
        setMessage("We could not send your application. Try again in a moment.");
      }
    }
  }

  if (phase === "done") return <Success job={job} />;

  return (
    <form onSubmit={onSubmit} noValidate={false} className="space-y-5">
      {message && (
        <p
          // `key` on the attempt so a repeated identical message is re-announced rather
          // than skipped as unchanged text.
          key={attempt}
          role="alert"
          className="rounded-[var(--radius-card)] border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          {message}
        </p>
      )}

      <Field
        id={`${formId}-name`}
        name="full_name"
        label="Full name"
        autoComplete="name"
        required
        disabled={busy}
        error={fieldErrors.full_name}
      />
      <Field
        id={`${formId}-email`}
        name="email"
        type="email"
        label="Email address"
        autoComplete="email"
        required
        disabled={busy}
        error={fieldErrors.email}
        hint="We will reply to this address."
      />

      <div>
        <PhoneField
          id={`${formId}-phone`}
          name="phone"
          label="Phone number"
          required
          defaultCountry={job.country_code || "NG"}
        />
        {fieldErrors.phone && <FieldError>{fieldErrors.phone}</FieldError>}
      </div>

      {job.locations.length > 0 && (
        <div>
          <label htmlFor={`${formId}-location`} className="block text-sm font-medium text-foreground">
            Which location are you applying for?
          </label>
          <select
            id={`${formId}-location`}
            name="location"
            required
            disabled={busy}
            defaultValue=""
            className={`${inputClass} mt-1.5`}
          >
            <option value="" disabled>
              Choose a location
            </option>
            {job.locations.map((location) => (
              <option key={location.id} value={location.id}>
                {location.label}
              </option>
            ))}
          </select>
          {fieldErrors.location && <FieldError>{fieldErrors.location}</FieldError>}
        </div>
      )}

      <ResumeField
        id={`${formId}-cv`}
        inputRef={fileInput}
        file={file}
        error={fileError}
        disabled={busy}
        uploading={phase === "uploading"}
        progress={progress}
        uploaded={Boolean(uploadedKey.current)}
        onChoose={chooseFile}
      />

      <div>
        <label htmlFor={`${formId}-cover`} className="block text-sm font-medium text-foreground">
          Cover letter <span className="font-normal text-muted">(optional)</span>
        </label>
        <textarea
          id={`${formId}-cover`}
          name="cover_letter"
          rows={6}
          maxLength={COVER_LETTER_MAX}
          disabled={busy}
          value={coverLetter}
          onChange={(event) => setCoverLetter(event.target.value)}
          placeholder="Tell us why this role, and what you would bring to it."
          className={`${inputClass} mt-1.5 resize-y`}
        />
        <div className="mt-1 flex justify-between text-xs text-muted">
          <span>{fieldErrors.cover_letter ?? "A short paragraph is plenty."}</span>
          {/* Only once it is worth knowing about — a counter from character one reads as
              a minimum to reach. */}
          {coverLetter.length > COVER_LETTER_MAX - 500 && (
            <span className="tabular-nums">
              {COVER_LETTER_MAX - coverLetter.length} left
            </span>
          )}
        </div>
      </div>

      {/* THE HONEYPOT. Off-screen rather than `display:none` — some bots skip hidden
          fields specifically — and `tabIndex={-1}` plus `aria-hidden` keep it away from
          both keyboard and screen-reader users. The backend answers a filled one with
          201 and stores nothing, so a bot is never told it failed. */}
      <div aria-hidden className="absolute left-[-9999px] top-0 h-0 w-0 overflow-hidden">
        <label htmlFor={`${formId}-website`}>Website</label>
        <input id={`${formId}-website`} name="website" type="text" tabIndex={-1} autoComplete="off" />
      </div>

      <TurnstileWidget resetSignal={attempt} />

      <button
        type="submit"
        disabled={busy}
        className="w-full rounded-full bg-accent px-6 py-3.5 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-70 sm:w-auto sm:px-10"
      >
        {phase === "uploading"
          ? `Uploading your CV… ${progress}%`
          : phase === "submitting"
            ? "Sending your application…"
            : "Submit application"}
      </button>

      <p className="text-xs leading-relaxed text-muted">
        We use what you send here to consider you for this role and to contact you about
        it. Your CV is stored privately and is only ever seen by the people doing the
        hiring. Email{" "}
        <a href="mailto:careers@tokecosmetics.com" className="underline underline-offset-2">
          careers@tokecosmetics.com
        </a>{" "}
        to ask us to delete it.
      </p>
    </form>
  );
}

function Success({ job }: { job: Job }) {
  return (
    <div
      role="status"
      className="rounded-[var(--radius-card)] border border-accent/30 bg-accent/5 p-8 text-center sm:p-10"
    >
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-accent text-white" aria-hidden>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" className="h-6 w-6">
          <path d="m5 13 4 4L19 7" />
        </svg>
      </div>
      <h3 className="mt-5 font-display text-2xl text-foreground">Application received</h3>
      <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-muted">
        Thank you — your application for <strong className="text-foreground">{job.title}</strong>{" "}
        is with us, CV and all. We have emailed you a confirmation.
      </p>
      {/* DELIBERATELY NO DEADLINE. One person reads these; a promise of "within 5 days"
          in an automated message is a complaint waiting to arrive. */}
      <p className="mx-auto mt-3 max-w-md text-sm leading-relaxed text-muted">
        Our team reads every application. If your experience matches what the role needs,
        someone will be in touch to arrange a conversation.
      </p>
      <a
        href="/careers"
        className="mt-6 inline-block text-sm font-medium text-accent underline underline-offset-4"
      >
        See our other open roles
      </a>
    </div>
  );
}

function ResumeField({
  id,
  inputRef,
  file,
  error,
  disabled,
  uploading,
  uploaded,
  progress,
  onChoose,
}: {
  id: string;
  inputRef: React.RefObject<HTMLInputElement | null>;
  file: File | null;
  error: string | null;
  disabled: boolean;
  uploading: boolean;
  uploaded: boolean;
  progress: number;
  onChoose: (file: File | null) => void;
}) {
  const [dragging, setDragging] = useState(false);

  return (
    <div>
      {/* BOTH of these are real labels for the same input, and that is deliberate.
          Written as a <span>, the field's name ("Your CV") was not associated with the
          control at all — a screen reader announced only the drop zone's own wording,
          and a test looking the field up by its visible name could not find it. Two
          labels concatenate into one accessible name, which reads correctly here:
          "Your CV, PDF DOC or DOCX up to 5MB. Drop your CV here, or browse." */}
      <label htmlFor={id} className="block text-sm font-medium text-foreground">
        Your CV <span className="font-normal text-muted">(PDF, DOC or DOCX, up to 5MB)</span>
      </label>

      {/* A LABEL, not a div with a click handler: it makes the whole drop zone operate
          the file input natively, so keyboard and screen-reader users get the real
          control rather than a div pretending to be one. */}
      <label
        htmlFor={id}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          if (disabled) return;
          onChoose(event.dataTransfer.files?.[0] ?? null);
        }}
        className={[
          "mt-1.5 flex cursor-pointer flex-col items-center justify-center rounded-[var(--radius-card)] border border-dashed px-5 py-7 text-center transition-colors",
          disabled && "cursor-not-allowed opacity-60",
          error
            ? "border-red-300 bg-red-50"
            : dragging
              ? "border-accent bg-accent/5"
              : "border-line bg-beige hover:border-accent/40",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <input
          ref={inputRef}
          id={id}
          type="file"
          accept={RESUME_ACCEPT}
          disabled={disabled}
          required={!file}
          onChange={(event) => onChoose(event.target.files?.[0] ?? null)}
          className="sr-only"
          aria-describedby={error ? `${id}-error` : undefined}
        />
        {file ? (
          <>
            <span className="max-w-full truncate text-sm font-medium text-foreground">
              {file.name}
            </span>
            <span className="mt-1 text-xs text-muted">
              {formatSize(file.size)}
              {uploaded && " · uploaded"} · click to replace
            </span>
          </>
        ) : (
          <>
            <UploadIcon />
            <span className="mt-2 text-sm text-foreground">
              Drop your CV here, or <span className="text-accent underline underline-offset-2">browse</span>
            </span>
            <span className="mt-1 text-xs text-muted">
              PDF, DOC or DOCX · up to {formatSize(MAX_RESUME_BYTES)}
            </span>
          </>
        )}
      </label>

      {uploading && (
        <div className="mt-2">
          <div
            role="progressbar"
            aria-valuenow={progress}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Uploading your CV"
            className="h-1.5 overflow-hidden rounded-full bg-line"
          >
            <div
              className="h-full bg-accent transition-[width] duration-200"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {error && <FieldError id={`${id}-error`}>{error}</FieldError>}
    </div>
  );
}

function Field({
  id,
  name,
  label,
  type = "text",
  required,
  disabled,
  autoComplete,
  hint,
  error,
}: {
  id: string;
  name: string;
  label: string;
  type?: string;
  required?: boolean;
  disabled?: boolean;
  autoComplete?: string;
  hint?: string;
  error?: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-foreground">
        {label}
      </label>
      <input
        id={id}
        name={name}
        type={type}
        required={required}
        disabled={disabled}
        autoComplete={autoComplete}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        className={`${inputClass} mt-1.5 ${error ? "border-red-300" : ""}`}
      />
      {error ? (
        <FieldError id={`${id}-error`}>{error}</FieldError>
      ) : hint ? (
        <p id={`${id}-hint`} className="mt-1 text-xs text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

function FieldError({ id, children }: { id?: string; children: React.ReactNode }) {
  return (
    <p id={id} className="mt-1 text-xs text-red-600">
      {children}
    </p>
  );
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  return `${Math.max(1, Math.round(bytes / 1024))}KB`;
}

function UploadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-7 w-7 text-muted" aria-hidden>
      <path d="M12 16V4m0 0L8 8m4-4 4 4" />
      <path d="M4 16v2.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V16" />
    </svg>
  );
}
