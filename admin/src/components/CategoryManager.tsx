"use client";

/**
 * The categories page: an indented tree on the left, an edit form on the right.
 *
 * ── NO DRAG-AND-DROP, AND THAT IS A DECISION ────────────────────────────────────────
 *
 * 17a dropped drag-to-reparent rather than deferring it. A parent SELECT is the same
 * capability for 40 categories that are rarely reorganised, and it arrives without a drag
 * library, without a keyboard fallback to write, and without the pointer-precision problem
 * that a nested tree gives anyone using a trackpad. The select is also the only one of the
 * two that can state WHY a move is refused.
 *
 * The select hides the category itself and its descendants — the moves that would create a
 * cycle. That is a courtesy: `CategoryAdminSerializer.validate_parent` refuses them
 * server-side too, because a cycle hangs the storefront's breadcrumb walk and its
 * recursive tree serializer, and a select constrains a browser rather than a caller.
 */
import { startTransition, useActionState, useState } from "react";
import type { CategoryState } from "@/app/(shell)/categories/actions";
import { categoryDepth, eligibleParents, type CategoryRef } from "@/lib/category-tree";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export function CategoryManager({
  categories,
  counts,
  action,
}: {
  /** Already ordered parent-first by the page. */
  categories: CategoryRef[];
  counts: Record<number, number>;
  action: (prev: CategoryState, formData: FormData) => Promise<CategoryState>;
}) {
  const [selectedId, setSelectedId] = useState<number | null>(categories[0]?.id ?? null);

  const selected = categories.find((c) => c.id === selectedId) ?? null;

  if (!categories.length) {
    return (
      <p className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center text-sm text-muted">
        No categories yet.
      </p>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
      <div className="overflow-hidden rounded-[var(--radius-card)] border border-line">
        <ul>
          {categories.map((category) => {
            const depth = categoryDepth(category, categories);
            const count = counts[category.id] ?? 0;
            return (
              <li key={category.id} className="border-b border-line last:border-0">
                <button
                  type="button"
                  onClick={() => setSelectedId(category.id)}
                  aria-current={category.id === selectedId ? "true" : undefined}
                  className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface ${
                    category.id === selectedId ? "bg-accent/10" : ""
                  }`}
                  style={{ paddingLeft: `${12 + depth * 20}px` }}
                >
                  <span className={category.is_active ? "" : "text-muted line-through"}>
                    {category.name}
                  </span>
                  {!category.is_active && (
                    <span className="rounded border border-line px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted">
                      Hidden
                    </span>
                  )}
                  <span className="ml-auto text-xs text-muted">
                    {/* Product counts, because "can I safely hide this?" is the question
                        somebody actually has in front of a category tree. */}
                    {count === 1 ? "1 product" : `${count} products`}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      {selected && (
        // KEYED BY THE SELECTED CATEGORY, so picking a different one remounts the form.
        // That does two things at once: the uncontrolled inputs pick up the new values
        // (otherwise the previous category's name stays in the box, on a form quietly
        // pointed at a different record), and `useActionState` inside it resets — so a
        // "Saved Skincare." confirmation does not sit above the Haircare form.
        <CategoryForm
          key={selected.id}
          category={selected}
          categories={categories}
          action={action}
        />
      )}
    </div>
  );
}

function CategoryForm({
  category,
  categories,
  action,
}: {
  category: CategoryRef;
  categories: CategoryRef[];
  action: (prev: CategoryState, formData: FormData) => Promise<CategoryState>;
}) {
  const [state, formAction, pending] = useActionState(action, {});
  const selected = category;

  // CONTROLLED FIELDS + A MANUAL DISPATCH, and both halves are load-bearing. When a
  // native `<form action>` completes, React resets the form: uncontrolled fields snap
  // back to their defaultValue from the render BEFORE the save (the refreshed
  // categories arrive in a later commit), and even a controlled field can be left
  // desynced because React skips rewriting a DOM value it believes is unchanged. The
  // visible symptom was the worst possible one for this surface: save "Men → parent
  // Body", succeed, and watch the panel claim "No parent (top level)" while the tree
  // shows the truth — one trusting second Save away from silently undoing the move.
  // So the fields are controlled, and the submit handler calls the action dispatch
  // itself instead of handing React the `action` prop — no native form action, no
  // automatic reset. Seeded per category via the key={selected.id} remount above.
  const [name, setName] = useState(selected.name);
  const [slug, setSlug] = useState(selected.slug);
  const [parent, setParent] = useState(selected.parent === null ? "" : String(selected.parent));
  const [sortOrder, setSortOrder] = useState(String(selected.sort_order));
  const [isActive, setIsActive] = useState(selected.is_active);

  return (
    <>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const formData = new FormData(e.currentTarget);
            // The dispatch is an async action, so React requires a transition when it is
            // not invoked via the `action` prop — which is exactly what this avoids.
            startTransition(() => formAction(formData));
          }}
          className="h-fit rounded-[var(--radius-card)] border border-line p-4"
        >
          <input type="hidden" name="current_slug" value={selected.slug} />

          {state.error && (
            <p className="mb-3 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn">
              {state.error}
            </p>
          )}
          {state.saved && !state.error && !state.fieldErrors && (
            <p className="mb-3 rounded border border-ok/30 bg-ok/10 p-2 text-sm text-ok" role="status">
              Saved {state.saved}.
            </p>
          )}

          <div className="space-y-3">
            <label className="block text-xs text-muted">
              Name
              <input
                type="text"
                name="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={`mt-1 ${FIELD}`}
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
                onChange={(e) => setSlug(e.target.value)}
                className={`mt-1 ${FIELD}`}
              />
              <p className="mt-1 text-xs text-muted">
                Storefront URL: <span className="font-mono">/category/{selected.slug}</span>
              </p>
              {state.fieldErrors?.slug && (
                <p className="mt-1 text-xs text-warn">{state.fieldErrors.slug}</p>
              )}
            </label>

            <label className="block text-xs text-muted">
              Parent
              <select
                name="parent"
                value={parent}
                onChange={(e) => setParent(e.target.value)}
                className={`mt-1 ${FIELD}`}
              >
                <option value="">No parent (top level)</option>
                {eligibleParents(selected, categories).map((option) => (
                  <option key={option.id} value={option.id}>
                    {"— ".repeat(categoryDepth(option, categories))}
                    {option.name}
                  </option>
                ))}
              </select>
              {state.fieldErrors?.parent && (
                <p className="mt-1 text-xs text-warn">{state.fieldErrors.parent}</p>
              )}
            </label>

            <label className="block text-xs text-muted">
              Sort order
              <input
                type="text"
                inputMode="numeric"
                name="sort_order"
                value={sortOrder}
                onChange={(e) => setSortOrder(e.target.value)}
                className={`mt-1 ${FIELD}`}
              />
              <p className="mt-1 text-xs text-muted">Lower sorts first among siblings.</p>
              {state.fieldErrors?.sort_order && (
                <p className="mt-1 text-xs text-warn">{state.fieldErrors.sort_order}</p>
              )}
            </label>

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                name="is_active"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                className="h-4 w-4 rounded border-line"
              />
              Visible on the storefront
            </label>
          </div>

          <button
            type="submit"
            disabled={pending}
            className="mt-4 w-full rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            {pending ? "Saving…" : "Save category"}
          </button>
        </form>
    </>
  );
}
