import type { Metadata } from "next";
import Link from "next/link";
import { DeliveryPartners } from "@/components/config/DeliveryPartners";
import { ApiError } from "@/lib/api";
import type { AdminPartnerZoneRow, DeliveryPartnerRow } from "@/lib/partners";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Delivery partners" };

const PATH = "/settings/partners";

/** Delivery partners (Plan-39): BrandnPack's portal account and rate card, staff
 * side. The two halves sit behind different scopes — accounts are `settings.manage`
 * (Owner), zone rows are `products.manage` (Manager and above) — so each half
 * degrades to a note instead of taking the whole page down with one 403. */
export default async function DeliveryPartnersPage() {
  await requireAdmin(PATH);

  let partners: DeliveryPartnerRow[] = [];
  let partnersError: string | null = null;
  try {
    partners = await fetchWithAuthOrBounce<DeliveryPartnerRow[]>("/admin/partners/", PATH);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    partnersError =
      e.status === 403
        ? "Partner accounts are Owner-only — you can still see the rate card below."
        : "The partner accounts could not be loaded.";
  }

  let zones: AdminPartnerZoneRow[] = [];
  let zonesError: string | null = null;
  try {
    zones = await fetchWithAuthOrBounce<AdminPartnerZoneRow[]>("/admin/partner-zones/", PATH);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    zonesError =
      e.status === 403
        ? "Your role does not include managing partner rate cards."
        : "The partner rate card could not be loaded.";
  }

  return (
    <div>
      <Link href="/settings" className="text-sm text-muted hover:text-foreground">
        ← Settings
      </Link>
      <h1 className="mt-2 text-lg font-semibold tracking-tight">Delivery partners</h1>
      <p className="mt-1 text-sm text-muted">
        Couriers who maintain their own rate card through the partner portal
        (<code className="text-xs">/partner</code> on this domain). Their prices reach
        checkout directly — the switch here removes a partner everywhere at once.
      </p>

      <div className="mt-6">
        <DeliveryPartners
          partners={partners}
          partnersError={partnersError}
          zones={zones}
          zonesError={zonesError}
        />
      </div>
    </div>
  );
}
