import type { Metadata } from "next";
import Link from "next/link";
import { PaymentsConfig } from "@/components/config/PaymentsConfig";
import { ApiError } from "@/lib/api";
import type { BankAccountRow, GatewayCatalogEntry, GatewayRow } from "@/lib/money-config";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Payments" };

const PATH = "/settings/payments";

/** `/settings/payments` — bank accounts and gateways, behind `settings.manage` (Owner).
 *
 * Under Settings rather than beside Orders because `rbac.py` already filed the payout
 * account there: "settings covers the payout bank account, which is the single
 * highest-value target in the system". */
export default async function PaymentsSettingsPage() {
  await requireAdmin(PATH);

  const [accountsResult, gatewaysResult, catalogResult] = await Promise.allSettled([
    fetchWithAuthOrBounce<{ results: BankAccountRow[] } | BankAccountRow[]>(
      "/admin/bank-accounts/", PATH,
    ),
    fetchWithAuthOrBounce<{ results: GatewayRow[] } | GatewayRow[]>(
      "/admin/payment-gateways/", PATH,
    ),
    // The add-to-market menu. Degrades to [] (the add control hides itself) rather
    // than failing the page — same posture as the secondary fetches elsewhere.
    fetchWithAuthOrBounce<GatewayCatalogEntry[]>("/admin/payment-gateways/catalog/", PATH),
  ]);

  for (const r of [accountsResult, gatewaysResult, catalogResult]) {
    if (r.status === "rejected" && !(r.reason instanceof ApiError)) throw r.reason;
  }

  const unwrap = <T,>(r: PromiseSettledResult<{ results: T[] } | T[]>): T[] => {
    if (r.status !== "fulfilled") return [];
    return Array.isArray(r.value) ? r.value : (r.value?.results ?? []);
  };

  const failed = accountsResult.status === "rejected";
  const forbidden =
    accountsResult.status === "rejected" && (accountsResult.reason as ApiError).status === 403;

  return (
    <div>
      <div>
        <Link href="/settings" className="text-sm text-muted hover:text-foreground">
          ← Settings
        </Link>
        <h1 className="mt-2 text-lg font-semibold tracking-tight">Payments</h1>
        <p className="mt-1 text-sm text-muted">
          Where customers send money, and which methods each market offers.
        </p>
      </div>
      <div className="mt-6">
        {failed ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {forbidden
              ? "Only the Owner can view or change payment settings."
              : "The payment settings could not be loaded."}
          </p>
        ) : (
          <PaymentsConfig
            accounts={unwrap<BankAccountRow>(accountsResult)}
            gateways={unwrap<GatewayRow>(gatewaysResult)}
            catalog={unwrap<GatewayCatalogEntry>(catalogResult)}
          />
        )}
      </div>
    </div>
  );
}
