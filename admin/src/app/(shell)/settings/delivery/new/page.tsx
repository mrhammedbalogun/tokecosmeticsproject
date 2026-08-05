import type { Metadata } from "next";
import Link from "next/link";
import { NewDeliveryOption } from "@/components/config/NewDeliveryOption";
import type { RegionRow } from "@/lib/regions";
import type { CountryRef } from "@/lib/reference";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "New delivery option" };

/** `/settings/delivery/new` — the location-first create wizard.
 *
 * Regions for ALL countries in one unpaginated fetch (NG's 811 plus the level-1
 * rows for GB/US/CA — one small response beats per-country expands), grouped
 * client-side. */
export default async function NewDeliveryOptionPage() {
  const PATH = "/settings/delivery/new";
  await requireAdmin(PATH);

  const [regionsResult, countriesResult] = await Promise.allSettled([
    fetchWithAuthOrBounce<RegionRow[]>("/admin/regions/", PATH),
    fetchWithAuthOrBounce<CountryRef[]>("/meta/countries/", PATH),
  ]);

  const regions =
    regionsResult.status === "fulfilled" && Array.isArray(regionsResult.value)
      ? regionsResult.value
      : [];
  const countries =
    countriesResult.status === "fulfilled" && Array.isArray(countriesResult.value)
      ? countriesResult.value
      : [];

  return (
    <div>
      <div>
        <Link href="/settings/delivery" className="text-sm text-muted hover:text-fg">
          ← Delivery
        </Link>
        <h1 className="mt-2 text-lg font-semibold tracking-tight">New delivery option</h1>
        <p className="mt-1 text-sm text-muted">
          Pick where it is offered, then what it costs.
        </p>
      </div>
      <div className="mt-6">
        <NewDeliveryOption countries={countries} regions={regions} />
      </div>
    </div>
  );
}
