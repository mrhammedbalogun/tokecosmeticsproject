import Link from "next/link";
import { Thumb } from "@/components/combo/ProductPicker";
import type { ComboRow } from "@/lib/combos";

/**
 * The list. Every column answers a question somebody actually has: which bundle is this
 * (picture + name), is it live, how big is the box, where does it sell, and how deep is
 * the discount.
 *
 * THE MARKETS CELL SAYS "EVERYWHERE" IN WORDS. `Combo.available_countries` empty means
 * every market, not none — the same trap `AvailabilityPanel` exists to avoid — and a
 * blank cell reads as the opposite of what it means.
 */
export function ComboTable({ rows }: { rows: ComboRow[] }) {
  if (!rows.length) {
    return (
      <p className="rounded-[var(--radius-card)] border border-dashed border-line bg-surface p-8 text-center text-sm text-muted">
        No combos yet. <Link href="/combos/new" className="underline underline-offset-2">
          Create the first one
        </Link>
        .
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line">
      <table className="w-full min-w-[720px] border-collapse bg-surface text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-muted">
            <th className="px-3 py-2 font-medium">Combo</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 text-right font-medium">Items</th>
            <th className="px-3 py-2 text-right font-medium">Discount</th>
            <th className="px-3 py-2 font-medium">Markets</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b border-line last:border-0 hover:bg-accent/5">
              <td className="px-3 py-2">
                <Link href={`/combos/${row.slug}`} className="flex items-center gap-3">
                  <Thumb src={row.image_url} alt="" size={40} />
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{row.name}</span>
                    <span className="block truncate font-mono text-[11px] text-muted">
                      /combo/{row.slug}
                    </span>
                  </span>
                  {row.is_featured && (
                    <span className="ml-1 rounded-full bg-gold/15 px-2 py-0.5 text-[11px] text-gold">
                      Featured
                    </span>
                  )}
                </Link>
              </td>
              <td className="px-3 py-2">
                <StatusPill status={row.status} />
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{row.item_count}</td>
              <td className="px-3 py-2 text-right tabular-nums">
                {String(Number(row.discount_percent))}%
              </td>
              <td className="px-3 py-2 text-xs">
                {row.markets.length === 0 ? (
                  <span className="text-muted">Everywhere</span>
                ) : (
                  row.markets.join(", ")
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatusPill({ status }: { status: ComboRow["status"] }) {
  const tone =
    status === "active"
      ? "bg-accent/10 text-accent"
      : status === "draft"
        ? "bg-line text-muted"
        : "bg-warn/10 text-warn";
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${tone}`}>
      {status[0].toUpperCase() + status.slice(1)}
    </span>
  );
}
