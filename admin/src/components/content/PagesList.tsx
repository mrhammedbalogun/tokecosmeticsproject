"use client";

/**
 * The content index: every page, and — more importantly — what the storefront footer
 * would do with its eleven hard-coded links right now.
 *
 * ── THE RECONCILIATION IS THE FEATURE ───────────────────────────────────────────────
 *
 * Before Plan-19a those eleven links all rendered a stub reading "CMS content arrives in
 * Plan-19". After it, they resolve only if a page exists AND is published — the public API
 * answers 404 for a draft. So "eleven pages created" is not the finish line and this
 * screen refuses to imply it is: a draft counts as a dead link, in red, until it is live.
 */
import { useState, useTransition } from "react";
import Link from "next/link";
import { createPageAction } from "@/app/(shell)/content/actions";
import { deadFooterLinks, footerReport, type PageRow } from "@/lib/pages";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export function PagesList({ pages }: { pages: PageRow[] }) {
  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const dead = deadFooterLinks(pages);
  const report = footerReport(pages);

  const create = (e: React.FormEvent) => {
    e.preventDefault();
    setErrors({});
    setMessage(null);
    startTransition(async () => {
      const state = await createPageAction({ title, slug: slug || title });
      if (state.savedAt) {
        setTitle("");
        setSlug("");
      } else {
        setErrors(state.fieldErrors ?? {});
        setMessage(state.message ?? null);
      }
    });
  };

  return (
    <div className="space-y-6">
      <section
        className={`rounded-[var(--radius-card)] border p-4 ${
          dead.length ? "border-warn/40 bg-warn/5" : "border-ok/40 bg-ok/5"
        }`}
        role={dead.length ? "alert" : undefined}
      >
        <h2 className={`text-sm font-semibold ${dead.length ? "text-warn" : "text-ok"}`}>
          {dead.length
            ? `${dead.length} of 11 footer links are broken on the live shop`
            : "Every footer link resolves"}
        </h2>
        <p className="mt-1 text-sm text-muted">
          The storefront footer links to these eleven pages. A page that is missing —{" "}
          <strong>or still a draft</strong> — is a 404 for a customer.
        </p>
        <ul className="mt-3 flex flex-wrap gap-2">
          {report.map((row) => (
            <li key={row.slug}>
              <span
                className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${
                  row.state === "published"
                    ? "border-ok/40 text-ok"
                    : "border-warn/40 text-warn"
                }`}
                title={
                  row.state === "missing"
                    ? "No page with this slug exists"
                    : row.state === "draft"
                      ? "Exists but unpublished — the public API 404s a draft"
                      : "Live"
                }
              >
                /{row.slug}
                <span className="opacity-70">· {row.state}</span>
              </span>
            </li>
          ))}
        </ul>
      </section>

      <p className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <Link href="/content/banners" className="underline underline-offset-2 hover:text-accent">
          Banners and the homepage hero →
        </Link>
        <Link href="/content/reviews" className="underline underline-offset-2 hover:text-accent">
          Featured Google reviews →
        </Link>
      </p>

      <section className="rounded-[var(--radius-card)] border border-line p-4">
        <h2 className="text-sm font-semibold">New page</h2>
        <form onSubmit={create} className="mt-3 grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <label className="block text-xs text-muted">
            Title
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className={`mt-1 ${FIELD}`}
            />
            {errors.title && <p className="mt-1 text-xs text-warn">{errors.title}</p>}
          </label>
          <label className="block text-xs text-muted">
            Slug
            <input
              type="text"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="returns"
              className={`mt-1 ${FIELD}`}
            />
            <span className="mt-1 block text-xs text-muted">
              The URL: /page/<strong>{slug || "…"}</strong>
            </span>
            {errors.slug && <p className="mt-1 text-xs text-warn">{errors.slug}</p>}
          </label>
          <div className="flex items-start">
            <button
              type="submit"
              disabled={pending}
              className="mt-5 rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
            >
              {pending ? "Creating…" : "Create draft"}
            </button>
          </div>
        </form>
        {message && (
          <p className="mt-2 text-sm text-warn" role="alert">
            {message}
          </p>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold">
          {pages.length} {pages.length === 1 ? "page" : "pages"}
        </h2>
        {pages.length === 0 ? (
          <p className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center text-sm text-muted">
            No pages yet. Create the eleven the footer expects, above.
          </p>
        ) : (
          <div className="overflow-hidden rounded-[var(--radius-card)] border border-line">
            <table className="w-full text-sm">
              <thead className="bg-surface text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Page</th>
                  <th className="px-3 py-2 text-left font-medium">URL</th>
                  <th className="px-3 py-2 text-left font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {pages.map((page) => (
                  <tr key={page.id} className="border-t border-line">
                    <td className="px-3 py-2">
                      <Link
                        href={`/content/${page.slug}`}
                        className="underline underline-offset-2 hover:text-accent"
                      >
                        {page.title}
                      </Link>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-muted">
                      /page/{page.slug}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`rounded border px-1.5 py-0.5 text-xs ${
                          page.status === "published"
                            ? "border-ok/40 text-ok"
                            : "border-line text-muted"
                        }`}
                      >
                        {page.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
