import type { Metadata } from "next";
import Link from "next/link";
import { InventoryFilterForm } from "@/components/inventory/InventoryFilterForm";
import { InventoryGrid } from "@/components/inventory/InventoryGrid";
import { Pagination } from "@/components/Pagination";
import { ApiError } from "@/lib/api";
import {
  inventoryQueryString,
  parseInventoryFilters,
  type GridPage,
} from "@/lib/inventory";
import { pageCount } from "@/lib/pagination";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Inventory" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const PATH = "/inventory";

/**
 * `/inventory` — the variant × warehouse grid, behind `products.manage`.
 *
 * THE DAILY-USE SCREEN FOR NIGERIA, and the reason Plan-17c is worth doing. Everything
 * else in the plan is scaffolding around this table.
 *
 * NOT READ-AUDITED. Stock levels carry no personal data, so this sits with the catalogue
 * reads rather than with the order desk — see `apps/core/audit.py` for where that line is
 * drawn. The adjustments made FROM here are audited, which is the half that matters.
 *
 * `fetchWithAuthOrBounce`, never `fetchWithAuth`: a Server Component cannot persist a
 * rotated refresh token, and the writing fetcher would blacklist the old one with nowhere
 * to put the new.
 */
export default async function InventoryPage({ searchParams }: { searchParams: SearchParams }) {
  await requireAdmin(PATH);

  const raw = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (typeof value === "string") raw.set(key, value);
    else if (Array.isArray(value) && value[0] !== undefined) raw.set(key, value[0]);
  }
  const filters = parseInventoryFilters(raw);

  let page: GridPage | null = null;
  let error: string | null = null;
  try {
    const qs = inventoryQueryString(filters);
    page = await fetchWithAuthOrBounce<GridPage>(
      `/admin/stock/grid/${qs ? `?${qs}` : ""}`,
      PATH,
    );
  } catch (e) {
    // `redirect()` throws; rethrown so a merely-stale session is renewed rather than
    // shown an error page.
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include managing stock."
        : "The inventory could not be loaded.";
  }

  const warehouses = page?.warehouses ?? [];

  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Inventory</h1>
          <p className="mt-1 text-sm text-muted">
            What is on the shelf, per warehouse. Click a count to adjust it.
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Link
            href="/inventory/warehouses"
            className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
          >
            Warehouses
          </Link>
          <Link
            href="/inventory/import"
            className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
          >
            Import CSV
          </Link>
          {/* A download is a navigation, not a fetch — and it goes through the BFF, which
              attaches the admin token server-side. */}
          <a
            href="/api/admin/stock/export.csv"
            className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
          >
            Export CSV
          </a>
        </div>
      </div>

      <div className="mt-6">
        <InventoryFilterForm filters={filters} warehouses={warehouses} />
      </div>

      <div className="mt-4">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <>
            <p className="mb-2 text-xs text-muted">
              {page?.count ?? 0} {page?.count === 1 ? "variant" : "variants"}
              {filters.lowStock ? " at or below their threshold" : ""}
            </p>
            <InventoryGrid rows={page?.results ?? []} warehouses={warehouses} />
            <Pagination
              basePath={PATH}
              page={filters.page}
              total={pageCount(page?.count ?? 0)}
              buildQuery={(target) => inventoryQueryString({ ...filters, page: target })}
              label="Inventory pages"
            />
          </>
        )}
      </div>
    </div>
  );
}
