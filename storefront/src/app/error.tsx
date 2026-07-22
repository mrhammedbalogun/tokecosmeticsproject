"use client";
export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="mx-auto max-w-lg px-4 py-24 text-center">
      <h1 className="font-display text-4xl">Something went wrong</h1>
      <p className="mt-4 text-muted">Please try again. If it keeps happening, contact us.</p>
      <button onClick={reset} className="mt-8 rounded-[var(--radius-card)] bg-accent px-6 py-3 text-surface hover:bg-accent-strong transition-colors">
        Try again
      </button>
    </main>
  );
}
