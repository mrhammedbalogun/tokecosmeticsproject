import type { Metadata } from "next";
import Link from "next/link";
import { DeliveryOptions } from "@/components/config/DeliveryOptions";
import { ApiError } from "@/lib/api";
import type { DeliveryOptionRow } from "@/lib/money-config";
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

  return (
    <div>
      <div>
        <Link href="/settings" className="text-sm text-muted hover:text-fg">
          ← Settings
        </Link>
        <h1 className="mt-2 text-lg font-semibold tracking-tight">Delivery</h1>
        <p className="mt-1 text-sm text-muted">
          What each delivery option costs and how long it takes.
        </p>
      </div>
      <div className="mt-6">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <DeliveryOptions options={options} />
        )}
      </div>
    </div>
  );
}
