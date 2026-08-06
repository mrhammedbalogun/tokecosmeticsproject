"use client";

/**
 * One homepage product row's collection choice (Phase 3, 2026-08-06).
 *
 * The row itself is a shelf, not a banner: what the admin chooses is WHICH collection
 * fills it. "Built-in" means the storefront's original slug — deleting the override
 * section — so the zero-config homepage stays exactly what shipped. The row hides on
 * the shop while its collection is empty, and this editor says so instead of letting
 * somebody wonder where the section went.
 */
import { startTransition, useState } from "react";
import Link from "next/link";
import { saveRowCollectionAction, type RowKey } from "@/app/(shell)/home-content/actions";

export interface RowCollectionOption {
  name: string;
  slug: string;
  productCount: number;
}

export function RowCollectionEditor({
  row,
  defaultSlug,
  sectionId,
  currentSlug,
  options,
}: {
  row: RowKey;
  /** The built-in collection the storefront uses when nothing is chosen. */
  defaultSlug: string;
  /** The override section's id, when one exists. */
  sectionId: number | null;
  /** The override's slug, or null when the row is on its built-in. */
  currentSlug: string | null;
  options: RowCollectionOption[];
}) {
  const [choice, setChoice] = useState(currentSlug ?? "");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const chosenSlug = choice || defaultSlug;
  const chosen = options.find((o) => o.slug === chosenSlug);
  const dirty = choice !== (currentSlug ?? "");

  const save = () => {
    setPending(true);
    setMessage(null);
    startTransition(async () => {
      const state = await saveRowCollectionAction({
        sectionId,
        row,
        collection: choice || null,
      });
      setPending(false);
      setMessage(state.savedAt ? null : (state.message ?? "That could not be saved."));
    });
  };

  return (
    <div className="rounded-[var(--radius-card)] border border-line p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2">
          <span className="text-xs text-muted">Collection</span>
          <select
            value={choice}
            onChange={(e) => setChoice(e.target.value)}
            disabled={pending || options.length === 0}
            className="rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none"
          >
            <option value="">Built-in ({defaultSlug})</option>
            {options.map((o) => (
              <option key={o.slug} value={o.slug}>
                {o.name} — {o.productCount} product{o.productCount === 1 ? "" : "s"}
              </option>
            ))}
          </select>
        </label>
        {dirty && (
          <button
            type="button"
            onClick={save}
            disabled={pending}
            className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            {pending ? "Saving…" : "Save"}
          </button>
        )}
        <span className="flex-1" />
        <Link href="/products" className="text-xs underline underline-offset-2 hover:text-accent">
          Manage collections under Products
        </Link>
      </div>
      <p className="mt-2 text-xs text-muted">
        {options.length === 0
          ? "Collections could not be loaded (your role may not include products)."
          : chosen
            ? chosen.productCount > 0
              ? `Showing up to 8 of ${chosen.productCount} products from “${chosen.name}”.`
              : `“${chosen.name}” has no products yet, so the shop hides this row.`
            : `The “${chosenSlug}” collection has not been created yet, so the shop hides this row.`}
      </p>
      {message && (
        <p className="mt-2 rounded border border-warn/30 bg-warn/5 p-2 text-xs text-warn" role="alert">
          {message}
        </p>
      )}
    </div>
  );
}
