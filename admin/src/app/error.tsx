"use client";

/**
 * Root error boundary — catches what `(shell)/error.tsx` cannot: failures on the
 * unauthenticated pages (`/login`, `/totp`, `/accept-invite`) and in the shell layout
 * itself. Same design as the shell boundary; see the comments there. No app chrome
 * here because the layout that draws it may be the thing that failed.
 */
export default function RootError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-md rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-6">
        <h2 className="text-sm font-semibold">The admin hit an error.</h2>
        <p className="mt-2 text-sm text-muted">
          Retry — and if this keeps happening, wait a minute first; a rate-limited
          session recovers on its own.
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
    </main>
  );
}
