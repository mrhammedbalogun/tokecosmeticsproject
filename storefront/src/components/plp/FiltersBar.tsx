import type { BrandRow } from "@/lib/catalog";
import type { PlpState } from "@/components/plp/plpParams";
import { SortSelect } from "@/components/plp/SortSelect";

/** GET-method form: submitting rewrites the URL params (SSR round-trip, no JS
 * required). Hidden inputs preserve context params owned by the page (tag/collection). */
export function FiltersBar({ base, state, brands, showBrand = true, resultCount }: {
  base: string; state: PlpState; brands: BrandRow[]; showBrand?: boolean; resultCount: number;
}) {
  return (
    <form method="GET" action={base}
      className="flex flex-wrap items-end gap-3 rounded-[var(--radius-card)] bg-surface p-4 shadow-sm">
      {state.tag && <input type="hidden" name="tag" value={state.tag} />}
      {state.collection && <input type="hidden" name="collection" value={state.collection} />}
      {showBrand && (
        <label className="text-xs text-muted">
          Brand
          <select name="brand" defaultValue={state.brand ?? ""}
            className="mt-1 block rounded-md border border-line bg-surface px-2 py-1.5 text-sm text-foreground">
            <option value="">All brands</option>
            {brands.map((b) => <option key={b.slug} value={b.slug}>{b.name}</option>)}
          </select>
        </label>
      )}
      <label className="text-xs text-muted">
        Min price
        <input name="price_min" type="number" min="0" step="any" defaultValue={state.price_min ?? ""}
          className="mt-1 block w-24 rounded-md border border-line px-2 py-1.5 text-sm text-foreground" />
      </label>
      <label className="text-xs text-muted">
        Max price
        <input name="price_max" type="number" min="0" step="any" defaultValue={state.price_max ?? ""}
          className="mt-1 block w-24 rounded-md border border-line px-2 py-1.5 text-sm text-foreground" />
      </label>
      <SortSelect current={state.ordering ?? "newest"} />
      <button type="submit"
        className="rounded-full bg-accent px-5 py-2 text-sm font-medium text-surface transition-colors hover:bg-accent-strong">
        Apply
      </button>
      <a href={base} className="text-sm text-muted underline hover:text-foreground">Clear</a>
      <span className="ml-auto text-sm text-muted" aria-live="polite">{resultCount} products</span>
    </form>
  );
}
