"use client";

/**
 * The error boundary for every admin page. Until 2026-08-10 there was NONE anywhere in
 * the app, so any uncaught throw — a dropped Server Function request, a render-time
 * rejection — landed on Next's bare "Application error" screen with no way back but a
 * hard reload. Staff read that as the admin crashing.
 *
 * Placed inside `(shell)` so the sidebar and topbar survive the failure: the person
 * keeps their navigation, and only the page segment is replaced.
 *
 * `unstable_retry`, not `reset` (Next 16.2): retry RE-FETCHES the segment before
 * re-rendering, which is the recovery that actually works when the failure was a
 * throttled or dropped fetch. `reset` alone would re-render the same dead data.
 *
 * The error itself is not rendered: in production Next redacts server error messages
 * anyway, and this origin deliberately has no error-reporting script (see
 * next.config.ts — zero third-party scripts). The digest is shown so a report from a
 * staff member can be matched to the server log line that carries the same digest.
 */
export default function ShellError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  return (
    <div className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-6">
      <h2 className="text-sm font-semibold">This page hit an error.</h2>
      <p className="mt-2 text-sm text-muted">
        Nothing already saved was affected. Retry — and if this keeps happening, wait a
        minute first; a rate-limited session recovers on its own.
      </p>
      {error.digest && (
        <p className="mt-2 font-mono text-xs text-muted">Reference: {error.digest}</p>
      )}
      <button
        type="button"
        onClick={() => unstable_retry()}
        className="mt-4 rounded bg-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90"
      >
        Try again
      </button>
    </div>
  );
}
