import type { Metadata } from "next";
import Link from "next/link";
import { TaxSettings } from "@/components/config/TaxSettings";
import { ApiError } from "@/lib/api";
import type { TaxCountryRow, TaxSettingsRow } from "@/lib/tax-config";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Taxes" };

const PATH = "/settings/taxes";

export default async function TaxSettingsPage() {
  await requireAdmin(PATH);

  let settings: TaxSettingsRow | null = null;
  let countries: TaxCountryRow[] = [];
  let error: string | null = null;
  try {
    [settings, countries] = await Promise.all([
      fetchWithAuthOrBounce<TaxSettingsRow>("/admin/tax/settings/", PATH),
      fetchWithAuthOrBounce<TaxCountryRow[]>("/admin/tax/countries/", PATH),
    ]);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include managing tax settings."
        : "The tax settings could not be loaded.";
  }

  return (
    <div>
      <Link href="/settings" className="text-sm text-muted hover:text-foreground">
        ← Settings
      </Link>
      <h1 className="mt-2 text-lg font-semibold tracking-tight">Taxes</h1>
      <p className="mt-1 text-sm text-muted">
        Whether tax is charged, and what each market charges. Prices marked “include
        tax” never change what the customer pays — the tax line only names the portion
        already inside the price.
      </p>

      <div className="mt-6">
        {error || !settings ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error ?? "The tax settings could not be loaded."}
          </p>
        ) : (
          <TaxSettings settings={settings} countries={countries} />
        )}
      </div>
    </div>
  );
}
