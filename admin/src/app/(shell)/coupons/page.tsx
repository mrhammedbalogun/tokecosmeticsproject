import type { Metadata } from "next";
import { CouponManager } from "@/components/config/CouponManager";
import { ApiError } from "@/lib/api";
import type { CouponRow } from "@/lib/money-config";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";

export const metadata: Metadata = { title: "Coupons" };

const PATH = "/coupons";

/** The configured currencies, as on the products list. */
const CURRENCIES = ["NGN", "GBP", "USD", "CAD"];

/** `/coupons` — behind `marketing.manage`, matching the nav item that has pointed here
 *  since Plan-16 and 404'd ever since. */
export default async function CouponsPage() {
  await requireAdmin(PATH);

  let coupons: CouponRow[] = [];
  let error: string | null = null;
  try {
    const data = await fetchWithAuthOrBounce<{ results: CouponRow[] } | CouponRow[]>(
      "/admin/coupons/", PATH,
    );
    coupons = Array.isArray(data) ? data : (data?.results ?? []);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    error =
      e.status === 403
        ? "Your role does not include managing coupons."
        : "The coupons could not be loaded.";
  }

  return (
    <div>
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Coupons</h1>
        <p className="mt-1 text-sm text-muted">
          Discount codes customers type at checkout.
        </p>
      </div>
      <div className="mt-6">
        {error ? (
          <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
            {error}
          </p>
        ) : (
          <CouponManager coupons={coupons} currencies={CURRENCIES} />
        )}
      </div>
    </div>
  );
}
