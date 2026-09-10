/**
 * The Details tab. PRESENTATIONAL: it owns no state, receives values and one `onChange`,
 * and is rendered by `ProductEditor`.
 *
 * That split is 17a design decision 3's consequence, spelled out in the spec: if the
 * editor grows unwieldy, extract each tab's PANEL — never give each tab its own form
 * state, which reintroduces the problem the decision exists to avoid.
 */
import { RichTextField } from "@/components/RichTextField";
import { STATUSES, type ProductFormValues, type EditableField } from "@/lib/product-form";
import { categoryDepth, type CategoryRef, type TagRef } from "@/lib/reference";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-muted/70 focus:border-accent focus:outline-none";

function label(status: string) {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export interface PanelProps {
  values: ProductFormValues;
  errors: Partial<Record<EditableField, string>>;
  onChange: <K extends keyof ProductFormValues>(field: K, value: ProductFormValues[K]) => void;
}

function Error({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="mt-1 text-xs text-warn">{message}</p>;
}

export function DetailsPanel({
  values,
  errors,
  onChange,
  categories,
  tags,
}: PanelProps & { categories: CategoryRef[]; tags: TagRef[] }) {
  /**
   * What the picker offers. HIDDEN CATEGORIES ARE LEFT OUT unless this product is already
   * in one.
   *
   * Not cosmetic: the 2026-09-10 menu rework retired 26 of production's 40 categories
   * (deactivated, not deleted, so their old assignments survive). Listed, they came FIRST
   * — they lost their parents, so they sort as roots — and pushed all twelve assignable
   * ones out of a 224px scroll box. The job this control exists for is filing products
   * into the new menu, and it was showing a wall of struck-through dead ends instead.
   *
   * A hidden category is also not a place a product can usefully go: the storefront's tree
   * endpoint only returns active rows, so ticking one files the product nowhere. The
   * already-ticked exception is what keeps such an assignment removable.
   */
  const pickable = categories.filter(
    (category) => category.is_active || values.categories.includes(category.id),
  );

  const toggle = (list: number[], id: number) =>
    list.includes(id) ? list.filter((x) => x !== id) : [...list, id];

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <label className="block text-xs text-muted">
        Name
        <input
          type="text"
          value={values.name}
          onChange={(e) => onChange("name", e.target.value)}
          className={`mt-1 ${FIELD}`}
        />
        <Error message={errors.name} />
      </label>

      <label className="block text-xs text-muted">
        Slug
        <input
          type="text"
          value={values.slug}
          onChange={(e) => onChange("slug", e.target.value)}
          className={`mt-1 ${FIELD}`}
        />
        {/* Said plainly, because it is not reversible by undo: the storefront URL is
            built from this, and Plan-24's redirect map covers old URL SHAPES, not old
            slugs. Changing it breaks any link anybody already has. */}
        <p className="mt-1 text-xs text-muted">
          Changes the storefront URL. Existing links to this product will stop working.
        </p>
        <Error message={errors.slug} />
      </label>

      <label className="block text-xs text-muted">
        Status
        <select
          value={values.status}
          onChange={(e) => onChange("status", e.target.value as ProductFormValues["status"])}
          className={`mt-1 ${FIELD}`}
        >
          {STATUSES.map((status) => (
            <option key={status} value={status}>
              {label(status)}
            </option>
          ))}
        </select>
        <Error message={errors.status} />
      </label>

      <label className="flex items-center gap-2 self-end text-sm">
        <input
          type="checkbox"
          checked={values.is_featured}
          onChange={(e) => onChange("is_featured", e.target.checked)}
          className="h-4 w-4 rounded border-line"
        />
        Featured
      </label>

      {/* Rich text (TipTap) since 2026-08-12 by owner request, superseding the earlier
          plain-textarea ruling. The stored value is still the same HTML string; the
          backend sanitises it on write through the CMS allow-list. */}
      <div className="lg:col-span-2">
        <RichTextField
          label="Short description"
          value={values.short_description}
          onChange={(v) => onChange("short_description", v)}
          rows={2}
          error={errors.short_description}
        />
      </div>

      <div className="lg:col-span-2">
        <RichTextField
          label="Description"
          value={values.description}
          onChange={(v) => onChange("description", v)}
          rows={8}
          error={errors.description}
        />
      </div>

      <fieldset className="lg:col-span-1">
        <legend className="text-xs text-muted">Categories</legend>
        <p className="mt-1 text-xs text-muted">
          Where this product appears in the shop menu. Tick as many as fit.
        </p>
        {/* Taller than the Tags box beside it: the menu is fourteen rows (twelve
            shelves and two headings) and a 224px window showed half of them. */}
        <div className="mt-1 max-h-80 overflow-y-auto rounded border border-line bg-surface p-2">
          {pickable.length === 0 ? (
            <p className="p-2 text-xs text-muted">No categories yet.</p>
          ) : (
            pickable.map((category) => {
              const indent = `${categoryDepth(category, categories) * 16}px`;
              // A MENU HEADING — "Shop By Skin Concerns" — gathers the rows under it and
              // holds no products itself. Rendered as a label, not a disabled checkbox: a
              // greyed-out box invites clicking and says nothing about why it will not
              // tick, whereas a heading reads as the thing it is and orients the four
              // choices below it.
              const ticked = values.categories.includes(category.id);
              // …unless this product is already filed on the heading, in which case it
              // keeps its checkbox so the assignment can be UNDONE. Hiding it would leave
              // the product showing on a group page with no control anywhere to take it
              // off — the trap `rebuild_shop_menu` clears once, and that a later
              // heading-flip would recreate.
              if (category.is_assignable === false && !ticked) {
                return (
                  <p
                    key={category.id}
                    style={{ paddingLeft: indent }}
                    className="pt-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted"
                  >
                    {category.name}
                  </p>
                );
              }
              return (
                <label
                  key={category.id}
                  className="flex items-center gap-2 py-0.5 text-sm"
                  style={{ paddingLeft: indent }}
                >
                  <input
                    type="checkbox"
                    checked={ticked}
                    onChange={() => onChange("categories", toggle(values.categories, category.id))}
                    className="h-4 w-4 rounded border-line"
                  />
                  <span className={category.is_active ? "" : "text-muted line-through"}>
                    {category.name}
                    {category.is_assignable === false && (
                      <span className="ml-1 text-xs text-warn">
                        — a heading; untick to remove
                      </span>
                    )}
                  </span>
                </label>
              );
            })
          )}
        </div>
        <Error message={errors.categories} />
      </fieldset>

      <fieldset className="lg:col-span-1">
        <legend className="text-xs text-muted">Tags</legend>
        <div className="mt-1 max-h-56 overflow-y-auto rounded border border-line bg-surface p-2">
          {tags.length === 0 ? (
            <p className="p-2 text-xs text-muted">No tags yet.</p>
          ) : (
            tags.map((tag) => (
              <label key={tag.id} className="flex items-center gap-2 py-0.5 text-sm">
                <input
                  type="checkbox"
                  checked={values.tags.includes(tag.id)}
                  onChange={() => onChange("tags", toggle(values.tags, tag.id))}
                  className="h-4 w-4 rounded border-line"
                />
                {tag.name}
              </label>
            ))
          )}
        </div>
        <Error message={errors.tags} />
      </fieldset>
    </div>
  );
}
