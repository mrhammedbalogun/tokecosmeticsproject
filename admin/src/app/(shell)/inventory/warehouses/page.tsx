import type { Metadata } from "next";
import Link from "next/link";
import { WarehouseManager } from "@/components/inventory/WarehouseManager";
import { ApiError } from "@/lib/api";
import type { CountryRef } from "@/lib/reference";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";
import type { WarehouseRow } from "@/lib/warehouses";

export const metadata: Metadata = { title: "Warehouses" };

const PATH = "/inventory/warehouses";

/**
 * `/inventory/warehouses` — where stock physically is, behind `products.manage`.
 *
 * UNDER `/inventory` RATHER THAN ITS OWN NAV ENTRY: a warehouse is not a thing anybody
 * comes looking for on its own, it is the answer to a question the inventory grid raised
 * ("why is there a UK column?", "why did this go to Lagos?"). The grid links here.
 *
 * `fetchWithAuthOrBounce`, never `fetchWithAuth`: a Server Component cannot persist a
 * rotated refresh token.
 */
export default async function WarehousesPage() {
  await requireAdmin(PATH);

  const [warehousesResult, countriesResult] = await Promise.allSettled([
    fetchWithAuthOrBounce<{ results: WarehouseRow[] } | WarehouseRow[]>(
      "/admin/warehouses/",
      PATH,
    ),
    fetchWithAuthOrBounce<CountryRef[]>("/meta/countries/", PATH),
  ]);

  for (const result of [warehousesResult, countriesResult]) {
    // `redirect()` throws; rethrown so a merely-stale session is renewed rather than
    // shown an error page.
    if (result.status === "rejected" && !(result.reason instanceof ApiError)) throw result.reason;
  }

  let error: string | null = null;
  if (warehousesResult.status === "rejected") {
    const e = warehousesResult.reason as ApiError;
    error =
      e.status === 403
        ? "Your role does not include managing warehouses."
        : "The warehouses could not be loaded.";
  }

  const payload = warehousesResult.status === "fulfilled" ? warehousesResult.value : null;
  const warehouses: WarehouseRow[] = Array.isArray(payload) ? payload : (payload?.results ?? []);
  // Losing the country list costs the checkboxes their labels, never the page.
  const countries =
    countriesResult.status === "fulfilled" && Array.isArray(countriesResult.value)
      ? countriesResult.value.map((c) => ({ code: c.code, name: c.name }))
      : [];

  return (
    <div>
      <div>
        <Link href="/inventory" className="text-sm text-muted hover:text-fg">
          ← Inventory
        </Link>
        <h1 className="mt-2 text-lg font-semibold tracking-tight">Warehouses</h1>
        <p className="mt-1 text-sm text-muted">
          Where stock physically sits, and which countries each place can fill orders for.
        </p>
      </div>

      <div className="mt-6">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <WarehouseManager warehouses={warehouses} countries={countries} />
        )}
      </div>
    </div>
  );
}
