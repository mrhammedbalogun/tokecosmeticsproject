"use client";

/**
 * The intake switch: whether tokecosmetics.com is taking programme applications.
 *
 * ── THE ONE CONTROL ON THIS ADMIN THAT EDITS THE PUBLIC SITE FROM A CHECKBOX ────────
 *
 * Saving here fires a storefront revalidation, so the form comes off the public page
 * within a second. That makes it worth being loud about: the card states which of the
 * two things is true right now in a full sentence, rather than leaving the operator to
 * read a checkbox and infer it.
 *
 * ── CLOSING ASKS FOR THE SENTENCE, OPENING DOES NOT ────────────────────────────────
 *
 * The message field only matters while closed, so it is only shown then — and the
 * backend supplies a sensible default if it is left blank, so an operator who closes the
 * intake in a hurry never produces a blank space where a form used to be.
 */
import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { saveProgrammeSettings } from "@/app/(shell)/entrepreneurship/actions";
import type { ProgrammeSettings } from "@/lib/entrepreneurship";

export function IntakeSwitch({ settings }: { settings: ProgrammeSettings }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [isOpen, setIsOpen] = useState(settings.is_open);
  const [message, setMessage] = useState(settings.closed_message);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // Dirty tracking, so "Save" is not offered on a card nobody has touched — and so the
  // "Saved." confirmation disappears the moment it stops being true.
  const dirty = isOpen !== settings.is_open || message !== settings.closed_message;

  function save() {
    startTransition(async () => {
      const result = await saveProgrammeSettings({
        is_open: isOpen,
        closed_message: message,
      });
      setError(result.message ?? null);
      setSaved(Boolean(result.savedAt));
      if (result.savedAt) router.refresh();
    });
  }

  return (
    <section className="rounded-[var(--radius-card)] border border-line bg-surface p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold">Applications</h2>
          <p className="mt-1 text-sm text-muted">
            {settings.is_open ? (
              <>
                The form is{" "}
                <span className="font-medium text-ok">live on the website</span> and
                students can apply right now.
              </>
            ) : (
              <>
                The form is{" "}
                <span className="font-medium text-warn">closed</span>. The page is still
                up; visitors see your message instead of the form.
              </>
            )}
          </p>
        </div>

        <label className="flex items-center gap-2.5 text-sm">
          <input
            type="checkbox"
            checked={isOpen}
            disabled={pending}
            onChange={(e) => {
              setIsOpen(e.target.checked);
              setSaved(false);
            }}
            className="h-4 w-4 rounded border-line accent-[var(--color-accent)]"
          />
          <span className="font-medium">Accepting applications</span>
        </label>
      </div>

      {!isOpen && (
        <label className="mt-5 block">
          <span className="text-sm font-medium">What visitors see instead</span>
          <span className="mt-0.5 block text-xs text-muted">
            Shown publicly, in place of the form. Leave it blank and we use a sensible
            default.
          </span>
          <textarea
            rows={2}
            maxLength={300}
            value={message}
            disabled={pending}
            placeholder="e.g. Applications reopen in January — check back then."
            onChange={(e) => {
              setMessage(e.target.value);
              setSaved(false);
            }}
            className="mt-2 w-full rounded-[var(--radius-card)] border border-line bg-surface px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/30"
          />
        </label>
      )}

      {error && (
        <p className="mt-3 rounded-[var(--radius-card)] border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="mt-4 flex items-center gap-3">
        <button
          type="button"
          disabled={pending || !dirty}
          onClick={save}
          className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
        >
          {pending ? "Saving…" : "Save"}
        </button>
        {saved && !dirty && (
          <span className="text-xs text-ok">Saved. The website is updated.</span>
        )}
        {dirty && !pending && (
          <span className="text-xs text-muted">Unsaved changes.</span>
        )}
      </div>
    </section>
  );
}
