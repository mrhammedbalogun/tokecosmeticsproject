import Link from "next/link";
export default function NotFound() {
  return (
    <main className="mx-auto max-w-lg px-4 py-24 text-center">
      <h1 className="font-display text-5xl">404</h1>
      <p className="mt-4 text-muted">We couldn&apos;t find that page.</p>
      <Link href="/" className="mt-8 inline-block rounded-[var(--radius-card)] bg-accent px-6 py-3 text-surface hover:bg-accent-strong transition-colors">
        Back to home
      </Link>
    </main>
  );
}
