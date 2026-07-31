"use client";

/**
 * The create form: a name, a slug, and nothing else.
 *
 * THE SLUG AUTO-FILLS FROM THE NAME UNTIL SOMEBODY EDITS IT, and then stops for good.
 * Silently rewriting a slug that was typed on purpose is the sort of thing noticed only
 * after the product is live and the URL is wrong.
 *
 * NO UNIQUENESS CHECK HERE. Only the database knows whether a slug is free; the backend's
 * refusal is rendered verbatim when it comes.
 */
import { useActionState, useState } from "react";
import Link from "next/link";
import { slugFollowsName, slugify } from "@/lib/slugify";
import type { CreateState } from "@/app/(shell)/products/new/actions";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none";

export function NewProductForm({
  action,
}: {
  action: (prev: CreateState, formData: FormData) => Promise<CreateState>;
}) {
  const [state, formAction, pending] = useActionState(action, {});

  const [name, setName] = useState(state.values?.name ?? "");
  const [slug, setSlug] = useState(state.values?.slug ?? "");
  // Tracks whether the slug is still following the name. Seeded from the returned values
  // so a rejected form does not start auto-rewriting a slug the person had chosen.
  const [linked, setLinked] = useState(slugFollowsName(name, slug));

  const onName = (value: string) => {
    setName(value);
    if (linked) setSlug(slugify(value));
  };

  const onSlug = (value: string) => {
    setSlug(value);
    setLinked(slugFollowsName(name, value));
  };

  return (
    <form action={formAction} className="max-w-lg">
      {state.error && (
        <p className="mb-4 rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-3 text-sm text-warn">
          {state.error}
        </p>
      )}

      <div className="space-y-4">
        <label className="block text-xs text-muted">
          Name
          <input
            type="text"
            name="name"
            value={name}
            onChange={(e) => onName(e.target.value)}
            placeholder="Carrot Shea Butter"
            autoFocus
            className={`mt-1 ${FIELD} ${state.fieldErrors?.name ? "border-warn" : ""}`}
          />
          {state.fieldErrors?.name && (
            <p className="mt-1 text-xs text-warn">{state.fieldErrors.name}</p>
          )}
        </label>

        <label className="block text-xs text-muted">
          Slug
          <input
            type="text"
            name="slug"
            value={slug}
            onChange={(e) => onSlug(e.target.value)}
            placeholder="carrot-shea-butter"
            className={`mt-1 ${FIELD} ${state.fieldErrors?.slug ? "border-warn" : ""}`}
          />
          <p className="mt-1 text-xs text-muted">
            The storefront URL: <span className="font-mono">/product/{slug || "…"}</span>
          </p>
          {state.fieldErrors?.slug && (
            <p className="mt-1 text-xs text-warn">{state.fieldErrors.slug}</p>
          )}
        </label>
      </div>

      <p className="mt-4 rounded-[var(--radius-card)] border border-line bg-surface p-3 text-sm text-muted">
        It is created as a <strong>draft</strong>. Everything else — description, images,
        prices, stock — is on the next screen, and it goes live when you set it to Active.
      </p>

      <div className="mt-4 flex items-center gap-2">
        <button
          type="submit"
          disabled={pending}
          className="rounded bg-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
        >
          {pending ? "Creating…" : "Create product"}
        </button>
        <Link href="/products" className="text-sm text-muted underline-offset-2 hover:underline">
          Cancel
        </Link>
      </div>
    </form>
  );
}
