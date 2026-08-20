import type { Metadata } from "next";
import Link from "next/link";
import { DeliveryControls } from "@/components/config/DeliveryControls";
import { ApiError } from "@/lib/api";
import type {
  DeliveryBlockRow,
  DeliveryFeeMaskRow,
  DeliveryServiceRef,
} from "@/lib/delivery-controls";
import type { RegionRow } from "@/lib/regions";
import type { CountryRef } from "@/lib/reference";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Delivery controls" };

const PATH = "/settings/delivery-controls";

/** Plan-41: the operator's veto and margin over every delivery service. Blocks are
 * subtractive — no rule means a service shows everywhere it already serves — and a
 * fee mask adds a percentage on top of the service's real fee at checkout. */
export default async function DeliveryControlsPage() {
  await requireAdmin(PATH);

  let services: DeliveryServiceRef[] = [];
  let blocks: DeliveryBlockRow[] = [];
  let masks: DeliveryFeeMaskRow[] = [];
  let error: string | null = null;
  try {
    [services, blocks, masks] = await Promise.all([
      fetchWithAuthOrBounce<DeliveryServiceRef[]>("/admin/delivery-services/", PATH),
      fetchWithAuthOrBounce<DeliveryBlockRow[]>("/admin/delivery-blocks/", PATH),
      fetchWithAuthOrBounce<DeliveryFeeMaskRow[]>("/admin/delivery-fee-masks/", PATH),
    ]);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include managing delivery."
        : "The delivery controls could not be loaded.";
  }

  // The block form's cascading pickers. Best-effort like the delivery tester: the
  // rules tables are the page's job, the add form degrades without its pickers.
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
      <Link href="/settings" className="text-sm text-muted hover:text-foreground">
        ← Settings
      </Link>
      <h1 className="mt-2 text-lg font-semibold tracking-tight">Delivery controls</h1>
      <p className="mt-1 text-sm text-muted">
        Block a delivery service in a country, state or LGA, and add a percentage on
        top of a service&apos;s fee. No rule means a service shows everywhere it
        already covers, at its real price.
      </p>

      <div className="mt-6">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <DeliveryControls
            services={services}
            blocks={blocks}
            masks={masks}
            countries={countries}
            regions={regions}
          />
        )}
      </div>
    </div>
  );
}
