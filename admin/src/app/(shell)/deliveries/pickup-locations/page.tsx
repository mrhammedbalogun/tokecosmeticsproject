import type { Metadata } from "next";
import Link from "next/link";
import { SenderLocations } from "@/components/config/SenderLocations";
import type { SenderLocationRow } from "@/app/(shell)/deliveries/pickup-locations/actions";
import { ApiError } from "@/lib/api";
import type { RegionRow } from "@/lib/regions";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Pickup locations" };

const PATH = "/deliveries/pickup-locations";

/**
 * `/deliveries/pickup-locations` — where carriers collect parcels (Plan-34, moved
 * here from /settings/delivery by Plan-35 so the list has ONE home). Managers and
 * Owners maintain it (`products.manage`); the card component is unchanged — the pin
 * stays the only routing input, state/LGA are display-only filing labels.
 */
export default async function PickupLocationsPage() {
  await requireAdmin(PATH);

  let rows: SenderLocationRow[] = [];
  let error: string | null = null;
  let states: { id: number; name: string }[] = [];
  try {
    // Regions ride the same load: the form's State dropdown (Plan-40) is the
    // canonical NG state list, and customer store pickup matches on it.
    const [data, regionsResult] = await Promise.all([
      fetchWithAuthOrBounce<SenderLocationRow[]>("/admin/sender-locations/", PATH),
      fetchWithAuthOrBounce<RegionRow[]>("/admin/regions/", PATH).catch(() => []),
    ]);
    rows = Array.isArray(data) ? data : [];
    states = (Array.isArray(regionsResult) ? regionsResult : [])
      .filter((r) => r.country_code === "NG" && r.level === "state")
      .map((r) => ({ id: r.id, name: r.name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include managing pickup locations."
        : "The pickup locations could not be loaded.";
  }

  return (
    <div>
      <Link href="/deliveries" className="text-sm text-muted hover:text-foreground">
        ← Deliveries
      </Link>
      <h1 className="mt-2 text-lg font-semibold tracking-tight">Pickup locations</h1>
      <p className="mt-1 text-sm text-muted">
        The Toke shops carriers collect parcels from. Every order ships from the nearest
        active location to the customer — the pin decides, and prices the quote. A
        location marked as a customer pickup store also appears at checkout as
        &ldquo;Pickup at Toke Cosmetics Store&rdquo; (free) for customers in its state.
      </p>

      <div className="mt-6">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <SenderLocations rows={rows} states={states} />
        )}
      </div>
    </div>
  );
}
