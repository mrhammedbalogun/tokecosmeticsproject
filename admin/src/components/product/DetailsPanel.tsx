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
   * The picker offers THE SHOP MENU AND NOTHING ELSE — every visible category a product
   * can actually be filed under.
   *
   * The 2026-09-10 rework retired 26 of production's 40 categories (deactivated, not
   * deleted, so their old assignments survive). The first cut of this filter kept a
   * retired row visible when the product was still in it, so the assignment stayed
   * removable. That was wrong at production's scale: ALL 69 products are in at least one
   * retired category and some are in sixteen, so the exception was not an exception — it
   * put a wall of struck-through dead ends on every product, which is what Hammed
   * reported on 2026-09-10. Leftover assignments are surfaced as one line below the box
   * instead (`strays`), which handles the same need without the noise.
   *
   * A retired category is also not a place a product can usefully go: the storefront's
   * tree endpoint returns active rows only, so ticking one files the product nowhere.
   */
  const pickable = categories.filter((category) => category.is_active);

  /**
   * Assignments the picker cannot show a checkbox for — a retired category, or a menu
   * heading like "Shop By Skin Concerns" that no longer accepts products.
   *
   * Surfaced rather than hidden, because it is real state: the rows stay in
   * `values.categories` and are saved back untouched, so a product is never silently
   * un-filed by opening its editor. What it must not be is INVISIBLE and unmanageable —
   * that is a product filed somewhere nobody can see or undo.
   */
  const strays = categories.filter(
    (category) =>
      values.categories.includes(category.id) &&
      (!category.is_active || category.is_assignable === false),
  );

  const clearStrays = () => {
    const stray = new Set(strays.map((c) => c.id));
    onChange("categories", values.categories.filter((id) => !stray.has(id)));
  };

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
        {/* Taller than the Tags box beside it, and tall enough for the WHOLE menu:
            fourteen rows — twelve shelves and two headings — is ~390px, and any window
            shorter than that hides the bottom of a list that now has a fixed, known
            length. The cap stays so a shop with thirty categories still scrolls. */}
        <div className="mt-1 max-h-[30rem] overflow-y-auto rounded border border-line bg-surface p-2">
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
              // A heading is ALWAYS a label, even when this product is filed on one: the
              // `strays` line below is what makes that assignment removable, so the list
              // itself stays a clean set of choices.
              if (category.is_assignable === false) {
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
                  <span>{category.name}</span>
                </label>
              );
            })
          )}
        </div>
        {strays.length > 0 && (
          <p className="mt-2 text-xs text-muted">
            Also filed in {strays.length}{" "}
            {strays.length === 1 ? "category" : "categories"} that{" "}
            {strays.length === 1 ? "is" : "are"} not in the menu (
            {strays.map((c) => c.name).join(", ")}) — shoppers cannot see{" "}
            {strays.length === 1 ? "it" : "them"}.{" "}
            <button
              type="button"
              onClick={clearStrays}
              className="underline hover:text-foreground"
            >
              Remove {strays.length === 1 ? "it" : "them"}
            </button>{" "}
            (takes effect on Save.)
          </p>
        )}
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
