/**
 * The products list table.
 *
 * A Server Component — every row is static and the only control is a link. Nothing to
 * hydrate, and nothing here is handed to a Client Component, so no row data reaches the
 * browser except what is rendered (the Plan-16 Task 8 lesson: props crossing into a Client
 * Component are serialised into the RSC payload in full, whether displayed or not).
 *
 * A PLAIN `<img>` RATHER THAN `next/image`, deliberately. These are 40px thumbnails on an
 * internal page behind an auth ceremony; the optimizer would add a per-image round trip
 * through the admin origin to save bytes nobody is paying for on a page nobody loads
 * cold. It also keeps `next.config.ts` free of a `remotePatterns` entry that would have to
 * track the media host in a second place — the CSP `img-src` already names it once.
 */
import Link from "next/link";
import { statusLabel, unpricedIn, type ProductRow } from "@/lib/products";

const STATUS_STYLE: Record<string, string> = {
  active: "border-ok/30 bg-ok/10 text-ok",
  draft: "border-line bg-surface text-muted",
  archived: "border-warn/30 bg-warn/5 text-warn",
};

export function ProductTable({
  rows,
  currencies,
}: {
  rows: ProductRow[];
  /** Configured currency codes, for the "not priced in" column. */
  currencies: readonly string[];
}) {
  if (!rows.length) {
    return (
      <p className="rounded-[var(--radius-card)] border border-line bg-surface p-6 text-center text-sm text-muted">
        No products match those filters.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-line bg-surface text-left text-xs text-muted">
            <th scope="col" className="p-3 font-medium">
              <span className="sr-only">Image</span>
            </th>
            <th scope="col" className="p-3 font-medium">Product</th>
            <th scope="col" className="p-3 font-medium">Status</th>
            <th scope="col" className="p-3 font-medium">Variants</th>
            <th scope="col" className="p-3 font-medium">Unpriced in</th>
            <th scope="col" className="p-3 font-medium">Updated</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const unpriced = unpricedIn(row, currencies);
            return (
              <tr key={row.id} className="border-b border-line last:border-0">
                <td className="p-3">
                  {row.thumbnail ? (
                    // eslint-disable-next-line @next/next/no-img-element -- see file header
                    <img
                      src={row.thumbnail}
                      alt=""
                      width={40}
                      height={40}
                      className="h-10 w-10 rounded object-cover"
                    />
                  ) : (
                    // Not an empty cell: "this product has no image" is a fact worth
                    // seeing on a catalogue where every product is supposed to have one.
                    <span
                      aria-label="No image"
                      title="No image"
                      className="flex h-10 w-10 items-center justify-center rounded border border-dashed border-line text-xs text-muted"
                    >
                      —
                    </span>
                  )}
                </td>
                <td className="p-3">
                  <Link
                    href={`/products/${row.slug}`}
                    className="font-medium underline-offset-2 hover:underline"
                  >
                    {row.name}
                  </Link>
                  {row.is_featured && (
                    <span className="ml-2 rounded border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-accent">
                      Featured
                    </span>
                  )}
                  <div className="text-xs text-muted">{row.slug}</div>
                </td>
                <td className="p-3">
                  <span
                    className={`rounded border px-2 py-0.5 text-xs ${
                      STATUS_STYLE[row.status] ?? STATUS_STYLE.draft
                    }`}
                  >
                    {statusLabel(row.status)}
                  </span>
                </td>
                <td className="p-3 tabular-nums">{row.variant_count}</td>
                <td className="p-3">
                  {unpriced.length ? (
                    <span className="text-xs text-warn">{unpriced.join(", ")}</span>
                  ) : (
                    <span className="text-xs text-muted">—</span>
                  )}
                </td>
                <td className="p-3 text-xs text-muted">
                  {/* `toISOString().slice(0, 10)` and not `toLocaleDateString`: the server
                      renders this, so a locale-formatted date would be the SERVER's locale
                      presented as the reader's. An ISO date is unambiguous everywhere. */}
                  {new Date(row.updated_at).toISOString().slice(0, 10)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
