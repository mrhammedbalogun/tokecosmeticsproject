import type { Metadata } from "next";
import Link from "next/link";
import { DeliveryOptions } from "@/components/config/DeliveryOptions";
import { DeliveryTester } from "@/components/config/DeliveryTester";
import { ApiError } from "@/lib/api";
import type { DeliveryOptionRow } from "@/lib/money-config";
import type { RegionRow } from "@/lib/regions";
import type { CountryRef } from "@/lib/reference";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Delivery" };

const PATH = "/settings/delivery";

export default async function DeliverySettingsPage() {
  await requireAdmin(PATH);

  let options: DeliveryOptionRow[] = [];
  let error: string | null = null;
  try {
    const data = await fetchWithAuthOrBounce<
      { results: DeliveryOptionRow[] } | DeliveryOptionRow[]
    >("/admin/delivery-options/", PATH);
    options = Array.isArray(data) ? data : (data?.results ?? []);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include managing delivery."
        : "The delivery options could not be loaded.";
  }

  // For the global address tester. Best-effort: the option list is the page's job,
  // the tester quietly absents itself if these fail.
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
      <div className="flex items-start justify-between gap-3">
        <div>
          <Link href="/settings" className="text-sm text-muted hover:text-foreground">
            ← Settings
          </Link>
          <h1 className="mt-2 text-lg font-semibold tracking-tight">Delivery</h1>
          <p className="mt-1 text-sm text-muted">
            What each delivery option costs and how long it takes.
          </p>
        </div>
        <Link
          href="/settings/delivery/new"
          className="mt-6 shrink-0 rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
        >
          Add delivery option
        </Link>
      </div>
      <div className="mt-6 space-y-6">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <DeliveryOptions options={options} countries={countries} />
        )}
        {countries.length > 0 && (
          <DeliveryTester countries={countries} regions={regions} />
        )}
      </div>
    </div>
  );
}
