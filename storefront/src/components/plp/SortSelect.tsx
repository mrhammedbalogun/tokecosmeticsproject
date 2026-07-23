"use client";
export function SortSelect({ current }: { current: string }) {
  return (
    <label className="text-xs text-muted">
      Sort
      <select name="ordering" defaultValue={current}
        onChange={(e) => e.currentTarget.form?.requestSubmit()}
        className="mt-1 block rounded-md border border-line bg-surface px-2 py-1.5 text-sm text-foreground">
        <option value="newest">Newest</option>
        <option value="best_selling">Best selling</option>
        <option value="price_asc">Price: low to high</option>
        <option value="price_desc">Price: high to low</option>
      </select>
    </label>
  );
}
