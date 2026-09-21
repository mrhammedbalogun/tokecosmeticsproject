"use client";

/**
 * The FAQ editor: every category, every question, on one screen.
 *
 * ── WHY IT IS ONE SCREEN AND NOT A LIST PLUS A DETAIL PAGE ──────────────────────────
 *
 * The pages editor splits them because a page body is long-form prose. An FAQ answer is
 * a paragraph or two, and the work is almost always comparative — "is this answered
 * anywhere else", "should this sit above that one", "what is still unanswered". Making
 * each of those a round trip through a detail route would turn a two-minute tidy-up into
 * twenty clicks.
 *
 * ── A QUESTION IS BORN UNPUBLISHED ──────────────────────────────────────────────────
 *
 * Adding one never puts it in front of a customer. The seeded policy questions arrive
 * the same way: the question is written down so it is not forgotten, and the answer is
 * the Owner's to write. Publishing is always a separate, deliberate act — and the action
 * refuses to publish an empty answer, because a blank accordion panel on the shop is
 * worse than a missing one.
 */
import { useState, useTransition } from "react";
import {
  createFaqCategoryAction,
  createFaqItemAction,
  deleteFaqItemAction,
  saveFaqCategoryAction,
  saveFaqItemAction,
} from "@/app/(shell)/content/faq/actions";
import type { FaqCategoryRow, FaqItemRow } from "@/lib/faq";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export function FaqEditor({
  groups,
}: {
  groups: { category: FaqCategoryRow; items: FaqItemRow[] }[];
}) {
  const [newCategory, setNewCategory] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const addCategory = (e: React.FormEvent) => {
    e.preventDefault();
    setMessage(null);
    startTransition(async () => {
      const state = await createFaqCategoryAction({ name: newCategory });
      if (state.savedAt) setNewCategory("");
      else setMessage(state.fieldErrors?.name ?? state.message ?? "Could not add that.");
    });
  };

  return (
    <div className="space-y-8">
      {groups.map(({ category, items }) => (
        <CategoryBlock key={category.id} category={category} items={items} />
      ))}

      <form onSubmit={addCategory} className="rounded-[var(--radius-card)] border border-dashed border-line p-4">
        <label className="block text-sm font-medium">Add a category</label>
        <p className="mt-0.5 text-xs text-muted">
          A heading on the FAQ page, such as &ldquo;Wholesale&rdquo;.
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          <input
            className={`${FIELD} max-w-xs`}
            value={newCategory}
            onChange={(e) => setNewCategory(e.target.value)}
            placeholder="Category name"
          />
          <button
            type="submit"
            disabled={pending || !newCategory.trim()}
            className="rounded bg-accent px-4 py-1.5 text-sm text-surface disabled:opacity-50"
          >
            Add
          </button>
        </div>
        {message && <p className="mt-2 text-xs text-warn">{message}</p>}
      </form>
    </div>
  );
}

function CategoryBlock({
  category,
  items,
}: {
  category: FaqCategoryRow;
  items: FaqItemRow[];
}) {
  const [name, setName] = useState(category.name);
  const [blurb, setBlurb] = useState(category.blurb);
  const [sort, setSort] = useState(String(category.sort));
  const [active, setActive] = useState(category.is_active);
  const [question, setQuestion] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const published = items.filter((i) => i.is_published).length;
  const live = category.is_active && published > 0;

  const saveCategory = () => {
    setMessage(null);
    startTransition(async () => {
      const state = await saveFaqCategoryAction({
        id: category.id, name, blurb, sort: Number(sort) || 0, is_active: active,
      });
      setMessage(state.savedAt ? "Saved." : (state.fieldErrors?.name ?? state.message ?? null));
    });
  };

  const addQuestion = (e: React.FormEvent) => {
    e.preventDefault();
    setMessage(null);
    startTransition(async () => {
      const state = await createFaqItemAction({
        category: category.id, question, answer_source: "",
      });
      if (state.savedAt) {
        setQuestion("");
        setMessage("Added as a draft — write the answer, then publish it.");
      } else {
        setMessage(state.fieldErrors?.question ?? state.message ?? "Could not add that.");
      }
    });
  };

  return (
    <section className="rounded-[var(--radius-card)] border border-line p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">{category.name}</h2>
        <span className={`text-xs ${live ? "text-muted" : "text-warn"}`}>
          {!category.is_active
            ? "hidden — category switched off"
            : published === 0
              ? "not on the shop yet — nothing published in it"
              : `${published} of ${items.length} live`}
        </span>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_5rem]">
        <label className="block">
          <span className="text-xs text-muted">Name</span>
          <input className={FIELD} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="block">
          <span className="text-xs text-muted">Blurb (optional)</span>
          <input className={FIELD} value={blurb} onChange={(e) => setBlurb(e.target.value)} />
        </label>
        <label className="block">
          <span className="text-xs text-muted">Order</span>
          <input className={FIELD} value={sort} onChange={(e) => setSort(e.target.value)} inputMode="numeric" />
        </label>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={active}
            onChange={(e) => setActive(e.target.checked)}
            className="h-4 w-4 rounded border-line"
          />
          Show this category on the shop
        </label>
        <button
          type="button"
          onClick={saveCategory}
          disabled={pending}
          className="rounded border border-line px-3 py-1 text-sm disabled:opacity-50"
        >
          Save category
        </button>
        {message && <span className="text-xs text-muted">{message}</span>}
      </div>

      <div className="mt-4 space-y-3">
        {items.map((item) => (
          <ItemRow key={item.id} item={item} />
        ))}
        {items.length === 0 && (
          <p className="text-xs text-muted">No questions in this category yet.</p>
        )}
      </div>

      <form onSubmit={addQuestion} className="mt-4 flex flex-wrap gap-2 border-t border-line pt-4">
        <input
          className={`${FIELD} max-w-md`}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Add a question to this category"
        />
        <button
          type="submit"
          disabled={pending || !question.trim()}
          className="rounded border border-line px-3 py-1.5 text-sm disabled:opacity-50"
        >
          Add question
        </button>
      </form>
    </section>
  );
}

function ItemRow({ item }: { item: FaqItemRow }) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState(item.question);
  const [answer, setAnswer] = useState(item.answer_source);
  const [sort, setSort] = useState(String(item.sort));
  const [publishedState, setPublished] = useState(item.is_published);
  const [message, setMessage] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [pending, startTransition] = useTransition();

  const save = (nextPublished = publishedState) => {
    setMessage(null);
    startTransition(async () => {
      const state = await saveFaqItemAction({
        id: item.id, question, answer_source: answer,
        sort: Number(sort) || 0, is_published: nextPublished,
      });
      if (state.savedAt) {
        setPublished(nextPublished);
        setMessage("Saved.");
      } else {
        setMessage(
          state.fieldErrors?.answer_source ?? state.fieldErrors?.question
          ?? state.message ?? "Could not save.",
        );
      }
    });
  };

  const remove = () => {
    startTransition(async () => {
      const state = await deleteFaqItemAction(item.id);
      if (!state.savedAt) setMessage(state.message ?? "Could not remove.");
    });
  };

  return (
    <div className="rounded border border-line">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm"
      >
        <span className="min-w-0 truncate">{question || "(no question)"}</span>
        <span className={`shrink-0 text-xs ${publishedState ? "text-accent" : "text-warn"}`}>
          {publishedState ? "live" : "draft"}
        </span>
      </button>

      {open && (
        <div className="space-y-2 border-t border-line p-3">
          <label className="block">
            <span className="text-xs text-muted">Question</span>
            <input className={FIELD} value={question} onChange={(e) => setQuestion(e.target.value)} />
          </label>
          <label className="block">
            <span className="text-xs text-muted">
              Answer — plain paragraphs, or simple HTML such as
              {" "}<code>&lt;p&gt;</code>, <code>&lt;ul&gt;</code>, <code>&lt;a&gt;</code>
            </span>
            <textarea
              className={`${FIELD} min-h-32 font-mono text-xs`}
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
            />
          </label>
          <label className="block max-w-24">
            <span className="text-xs text-muted">Order</span>
            <input className={FIELD} value={sort} onChange={(e) => setSort(e.target.value)} inputMode="numeric" />
          </label>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button
              type="button"
              onClick={() => save()}
              disabled={pending}
              className="rounded bg-accent px-3 py-1 text-sm text-surface disabled:opacity-50"
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => save(!publishedState)}
              disabled={pending}
              className="rounded border border-line px-3 py-1 text-sm disabled:opacity-50"
            >
              {publishedState ? "Unpublish" : "Save & publish"}
            </button>
            {/* Two clicks, no dialog: a question is cheap to retype and a modal for it
                would be more ceremony than the act deserves — but not one stray click. */}
            {confirming ? (
              <button
                type="button"
                onClick={remove}
                disabled={pending}
                className="rounded border border-warn/40 px-3 py-1 text-sm text-warn disabled:opacity-50"
              >
                Really remove
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setConfirming(true)}
                className="rounded border border-line px-3 py-1 text-sm text-muted"
              >
                Remove
              </button>
            )}
            {message && <span className="text-xs text-muted">{message}</span>}
          </div>

          {item.answer && item.answer !== item.answer_source && (
            // The allow-list dropped something. Said out loud rather than silently, so
            // an author can see that their <iframe> did not survive.
            <p className="text-xs text-muted">
              Some markup was removed when this was saved — the shop shows the cleaned
              version.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
