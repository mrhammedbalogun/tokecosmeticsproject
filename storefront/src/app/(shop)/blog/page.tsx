import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "The Journal — Toke Cosmetics" };

/** Placeholder so the approved nav never 404s; the real The Journal is on the roadmap. */
export default function Page() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-24 text-center">
      <h1 className="font-display text-4xl">The Journal</h1>
      <p className="mt-4 text-muted">
        We are putting the finishing touches on this. In the meantime, the whole
        collection is a click away.
      </p>
      <Link
        href="/products"
        className="mt-8 inline-block rounded-full bg-accent px-8 py-3.5 font-medium text-surface transition hover:bg-accent-strong"
      >
        Shop all products
      </Link>
    </div>
  );
}
