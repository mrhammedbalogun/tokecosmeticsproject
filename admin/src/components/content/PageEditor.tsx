"use client";

/**
 * The page editor.
 *
 * ── A TEXTAREA, NOT A BLOCK EDITOR, AND THAT IS A RECORDED DECISION ─────────────────
 *
 * The master spec says "rich text — use TipTap". Plan-19a ruling 1 declines it here: this
 * corpus is eleven pages of policy prose, the product editor already settled on a plain
 * HTML textarea labelled "HTML is allowed and is rendered as-is", and two authoring models
 * for two kinds of stored HTML is worse than one plain one. TipTap arrives in 19c, where
 * editorial homepage blocks want it, and this field swaps onto it then.
 *
 * ── THE SANITISER IS SHOWN, NOT HIDDEN ──────────────────────────────────────────────
 *
 * `body` comes back from the API already cleaned. When it differs from what was submitted,
 * the editor SAYS so — an author who pastes an `<iframe>` should learn that it was dropped
 * rather than wonder why the page looks wrong. Silent stripping is how people conclude the
 * software is broken.
 *
 * Controlled fields + a `startTransition` dispatch, for the reason the categories panel
 * learned: React resets a native form action on completion and the refreshed data lands a
 * commit later.
 */
import { startTransition, useState } from "react";
import { useRouter } from "next/navigation";
import { savePageAction } from "@/app/(shell)/content/actions";
import type { PageRow } from "@/lib/pages";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export function PageEditor({ page }: { page: PageRow }) {
  const router = useRouter();
  const [title, setTitle] = useState(page.title);
  const [slug, setSlug] = useState(page.slug);
  const [body, setBody] = useState(page.body_source);
  const [status, setStatus] = useState<"draft" | "published">(page.status);
  const [seoTitle, setSeoTitle] = useState(page.seo_title);
  const [seoDescription, setSeoDescription] = useState(page.seo_description);

  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);

  // What the storefront will actually render, as of the last save.
  const stripped = page.body_source.trim() !== "" && page.body !== page.body_source;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setPending(true);
    setSaved(false);
    setErrors({});
    setMessage(null);
    startTransition(async () => {
      const state = await savePageAction({
        currentSlug: page.slug,
        title,
        slug,
        body_source: body,
        status,
        seo_title: seoTitle,
        seo_description: seoDescription,
      });
      setPending(false);
      if (state.savedAt) {
        setSaved(true);
        // The slug is part of this page's own URL, so a change moves it.
        if (state.slug && state.slug !== page.slug) router.replace(`/content/${state.slug}`);
        else router.refresh();
      } else {
        setErrors(state.fieldErrors ?? {});
        setMessage(state.message ?? null);
      }
    });
  };

  return (
    <form onSubmit={submit} className="grid gap-6 lg:grid-cols-[1fr_20rem]">
      <div className="space-y-3">
        {message && (
          <p className="rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
            {message}
          </p>
        )}
        {saved && !message && (
          <p className="rounded border border-ok/30 bg-ok/10 p-2 text-sm text-ok" role="status">
            Saved.
          </p>
        )}

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
          Body
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={20}
            className={`mt-1 font-mono ${FIELD}`}
          />
          <span className="mt-1 block text-xs text-muted">
            HTML is allowed. Headings, paragraphs, lists, links, tables and images are kept;
            scripts, styles, iframes and forms are removed when you save.
          </span>
          {errors.body_source && (
            <p className="mt-1 text-xs text-warn">{errors.body_source}</p>
          )}
        </label>

        {stripped && (
          <p className="rounded border border-warn/30 bg-warn/5 p-2 text-xs text-warn">
            Some markup was removed when this page was last saved, because it is not on the
            allow-list. What the shop renders is shown below.
          </p>
        )}

        <details className="rounded border border-line p-2">
          <summary className="cursor-pointer text-xs text-muted">
            What the shop renders
          </summary>
          {/* The already-sanitised `body`, exactly as the storefront receives it. */}
          <div
            className="prose-sm mt-2 max-w-none text-sm leading-relaxed"
            dangerouslySetInnerHTML={{ __html: page.body }}
          />
        </details>
      </div>

      <div className="h-fit space-y-3 rounded-[var(--radius-card)] border border-line p-4">
        <label className="block text-xs text-muted">
          Status
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as "draft" | "published")}
            className={`mt-1 ${FIELD}`}
          >
            <option value="draft">Draft</option>
            <option value="published">Published</option>
          </select>
          <span className="mt-1 block text-xs text-muted">
            {status === "published"
              ? "Live on the shop."
              : "A draft is a 404 for customers — including from the footer."}
          </span>
        </label>

        <label className="block text-xs text-muted">
          Slug
          <input
            type="text"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            className={`mt-1 ${FIELD}`}
          />
          <span className="mt-1 block text-xs text-muted">
            /page/{slug} — changing it breaks existing links.
          </span>
          {errors.slug && <p className="mt-1 text-xs text-warn">{errors.slug}</p>}
        </label>

        <label className="block text-xs text-muted">
          SEO title
          <input
            type="text"
            value={seoTitle}
            onChange={(e) => setSeoTitle(e.target.value)}
            className={`mt-1 ${FIELD}`}
          />
          <span className="mt-1 block text-xs text-muted">Empty uses the page title.</span>
        </label>

        <label className="block text-xs text-muted">
          SEO description
          <textarea
            value={seoDescription}
            onChange={(e) => setSeoDescription(e.target.value)}
            rows={3}
            className={`mt-1 ${FIELD}`}
          />
        </label>

        <button
          type="submit"
          disabled={pending}
          className="w-full rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
        >
          {pending ? "Saving…" : "Save page"}
        </button>
        <p className="text-xs text-muted">
          Pages cannot be deleted — the shop links to them. Unpublish instead.
        </p>
      </div>
    </form>
  );
}
