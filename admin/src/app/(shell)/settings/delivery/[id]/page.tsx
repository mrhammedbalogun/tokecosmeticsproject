import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { CoveragePicker } from "@/components/config/CoveragePicker";
import { ApiError } from "@/lib/api";
import type { DeliveryOptionRow } from "@/lib/money-config";
import type { RegionRow } from "@/lib/regions";
import type { CountryRef } from "@/lib/reference";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Coverage" };

/** `/settings/delivery/{id}` — where one option is offered (Plan-19d).
 *
 * Its own page rather than a panel on the list: the tree is 811 rows for Nigeria, and it
 * is the one screen in Plan-19 that genuinely needs the room. */
export default async function CoveragePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const path = `/settings/delivery/${id}`;
  await requireAdmin(path);

  let option: DeliveryOptionRow;
  try {
    option = await fetchWithAuthOrBounce<DeliveryOptionRow>(
      `/admin/delivery-options/${encodeURIComponent(id)}/`, path,
    );
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (e.status === 404) notFound();
    throw e;
  }

  // ALL countries' regions in one unpaginated fetch (NG's 811 plus the level-1 rows
  // for GB/US/CA) — the picker groups them per country, so coverage is no longer an
  // NG-only affair.
  const [regionsResult, countriesResult] = await Promise.allSettled([
    fetchWithAuthOrBounce<RegionRow[]>("/admin/regions/", path),
    fetchWithAuthOrBounce<CountryRef[]>("/meta/countries/", path),
  ]);

  const regions = regionsResult.status === "fulfilled" ? (regionsResult.value ?? []) : [];
  const countries =
    countriesResult.status === "fulfilled" && Array.isArray(countriesResult.value)
      ? countriesResult.value
      : [];

  return (
    <div>
      <div>
        <Link href="/settings/delivery" className="text-sm text-muted hover:text-foreground">
          ← Delivery
        </Link>
        <h1 className="mt-2 text-lg font-semibold tracking-tight">{option.name}</h1>
        <p className="mt-1 text-sm text-muted">
          Which places this option is offered in.
        </p>
      </div>
      <div className="mt-6">
        <CoveragePicker
          optionId={option.id}
          optionName={option.name}
          countries={countries}
          regions={regions}
          selectedCountryCodes={option.country_codes}
          selectedRegionIds={option.region_ids}
        />
      </div>
    </div>
  );
}
