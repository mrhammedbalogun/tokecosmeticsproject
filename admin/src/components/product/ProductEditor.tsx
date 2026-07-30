"use client";

/**
 * The product editor shell: the tab strip, the form state every tab shares, and the save.
 *
 * ── TAB STATE IS LOCAL, NOT IN THE URL (17a design decision 3) ───────────────────────
 *
 * This deliberately contradicts `/settings/audit`, where filters live in the URL because
 * the URL should be the truth about what is on screen. A FORM is different: URL-driven
 * tabs make switching a NAVIGATION, and navigation destroys unsaved edits. Losing a
 * half-written description because somebody clicked "Availability" is a data-loss bug, not
 * a UX wrinkle. So the panels show and hide, and the cost — you cannot link to a tab — is
 * accepted.
 *
 * ── ONE COMPONENT OWNS THE STATE FOR EVERY TAB ──────────────────────────────────────
 *
 * The panels are presentational children taking values and an `onChange`. Giving each tab
 * its own form state would reintroduce exactly the problem the decision above avoids.
 *
 * ── WHAT SAVES WHEN (17a design decision 1) ─────────────────────────────────────────
 *
 * The product's own fields save together on Save. Variants, prices, images and stock are
 * separate resources that take effect immediately — and the UI must make that obvious
 * rather than hide it, which is what the unsaved-changes bar is for.
 */
import { useCallback, useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { AvailabilityPanel } from "@/components/product/AvailabilityPanel";
import { DetailsPanel } from "@/components/product/DetailsPanel";
import {
  isDirty,
  toFormValues,
  type EditableField,
  type ProductDetail,
  type ProductFormValues,
} from "@/lib/product-form";
import type { CategoryRef, CountryRef, TagRef } from "@/lib/reference";

export interface SaveResult {
  savedSlug?: string;
  savedAt?: number;
  errors?: { fields: Partial<Record<EditableField, string>>; banner?: string };
}

const TABS = [
  { id: "details", label: "Details" },
  { id: "availability", label: "Availability" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export function ProductEditor({
  product,
  categories,
  tags,
  countries,
  save,
}: {
  product: ProductDetail;
  categories: CategoryRef[];
  tags: TagRef[];
  countries: CountryRef[];
  /** The Server Function. Injected so the component is testable without a server. */
  save: (slug: string, values: ProductFormValues) => Promise<SaveResult>;
}) {
  const router = useRouter();
  const initial = useMemo(() => toFormValues(product), [product]);

  const [tab, setTab] = useState<TabId>("details");
  const [values, setValues] = useState<ProductFormValues>(initial);
  const [baseline, setBaseline] = useState<ProductFormValues>(initial);
  const [result, setResult] = useState<SaveResult>({});
  const [pending, startTransition] = useTransition();

  const dirty = isDirty(values, baseline);

  const onChange = useCallback(
    <K extends keyof ProductFormValues>(field: K, value: ProductFormValues[K]) => {
      setValues((current) => ({ ...current, [field]: value }));
      // The previous save's field errors stop being true the moment somebody edits. Left
      // on screen they read as "still wrong", and people re-fix a field that is now fine.
      setResult((current) => (current.errors ? {} : current));
    },
    [],
  );

  const onSave = () => {
    startTransition(async () => {
      const next = await save(baseline.slug, values);
      setResult(next);
      if (next.savedSlug) {
        // The saved values become the new baseline, so the bar clears without a refetch.
        setBaseline(values);
        // The slug is the URL. `replace`, not `push`: the old slug now 404s, so leaving it
        // in history gives the back button a broken page.
        if (next.savedSlug !== baseline.slug) {
          router.replace(`/products/${next.savedSlug}`);
        }
      }
    });
  };

  const errors = result.errors?.fields ?? {};

  return (
    <div>
      <div className="flex items-center gap-1 border-b border-line" role="tablist">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm ${
              tab === id
                ? "border-accent font-medium text-accent"
                : "border-transparent text-muted hover:text-fg"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {result.errors?.banner && (
        <p className="mt-4 rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-3 text-sm text-warn">
          {result.errors.banner}
        </p>
      )}

      <div className="mt-6">
        {tab === "details" && (
          <DetailsPanel
            values={values}
            errors={errors}
            onChange={onChange}
            categories={categories}
            tags={tags}
          />
        )}
        {tab === "availability" && (
          <AvailabilityPanel
            values={values}
            errors={errors}
            onChange={onChange}
            countries={countries}
          />
        )}
      </div>

      <div className="sticky bottom-0 mt-6 flex items-center gap-3 border-t border-line bg-bg/95 py-3 backdrop-blur">
        <button
          type="button"
          onClick={onSave}
          disabled={pending || !dirty}
          className="rounded bg-accent px-4 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
        >
          {pending ? "Saving…" : "Save"}
        </button>

        {dirty && !pending && (
          <span className="text-sm text-warn">Unsaved changes on this product.</span>
        )}
        {!dirty && result.savedAt && (
          <span className="text-sm text-ok" role="status">
            Saved.
          </span>
        )}
      </div>
    </div>
  );
}
