"use client";

/**
 * Coupons (Plan-19b). The model and its ledger have existed since Plan-08c; production
 * holds zero of both, because nothing could create one without a database client.
 *
 * THE LIST SAYS WHY A COUPON IS NOT WORKING. "Active" is a checkbox, but a code can be
 * ticked and still do nothing — not started, expired, or used up. A manager who has just
 * emailed a code to a mailing list needs that distinction immediately, not after a
 * customer complains.
 */
import { startTransition, useState } from "react";
import { createCouponAction, setCouponActiveAction } from "@/app/(shell)/coupons/actions";
import { couponInactiveReason, type CouponRow } from "@/lib/money-config";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export function CouponManager({
  coupons,
  currencies,
}: {
  coupons: CouponRow[];
  currencies: string[];
}) {
  const [code, setCode] = useState("");
  const [type, setType] = useState<"percent" | "fixed" | "free_shipping">("percent");
  const [value, setValue] = useState("10");
  const [currency, setCurrency] = useState(currencies[0] ?? "NGN");
  const [minSubtotal, setMinSubtotal] = useState("");
  const [usageLimit, setUsageLimit] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);

  const create = (e: React.FormEvent) => {
    e.preventDefault();
    setPending(true);
    setErrors({});
    setMessage(null);
    startTransition(async () => {
      const state = await createCouponAction({
        code, type, value, currency, min_subtotal: minSubtotal,
        usage_limit: usageLimit, ends_at: endsAt,
      });
      setPending(false);
      if (state.savedAt) {
        setCode("");
        setUsageLimit("");
        setEndsAt("");
      } else {
        setErrors(state.fieldErrors ?? {});
        setMessage(state.message ?? null);
      }
    });
  };

  const toggle = (coupon: CouponRow) => {
    setBusy(coupon.id);
    setMessage(null);
    startTransition(async () => {
      const state = await setCouponActiveAction(coupon.id, !coupon.is_active);
      setBusy(null);
      setMessage(state.message ?? null);
    });
  };

  return (
    <div className="space-y-6">
      {message && (
        <p className="rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
          {message}
        </p>
      )}

      <section className="rounded-[var(--radius-card)] border border-line p-4">
        <h2 className="text-sm font-semibold">New coupon</h2>
        <form onSubmit={create} className="mt-3 grid gap-3 sm:grid-cols-3">
          <label className="block text-xs text-muted">
            Code
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="WELCOME10"
              className={`mt-1 font-mono ${FIELD}`}
            />
            <span className="mt-1 block text-xs text-muted">Stored upper-case.</span>
            {errors.code && <p className="mt-1 text-xs text-warn">{errors.code}</p>}
          </label>

          <label className="block text-xs text-muted">
            Type
            <select
              value={type}
              onChange={(e) => setType(e.target.value as typeof type)}
              className={`mt-1 ${FIELD}`}
            >
              <option value="percent">Percentage off</option>
              <option value="fixed">Fixed amount off</option>
              <option value="free_shipping">Free shipping</option>
            </select>
          </label>

          {type !== "free_shipping" && (
            <label className="block text-xs text-muted">
              {type === "percent" ? "Percent off" : "Amount off"}
              <input
                type="text"
                inputMode="decimal"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                className={`mt-1 ${FIELD}`}
              />
              {errors.value && <p className="mt-1 text-xs text-warn">{errors.value}</p>}
            </label>
          )}

          {type === "fixed" && (
            <label className="block text-xs text-muted">
              Currency
              <select
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
                className={`mt-1 ${FIELD}`}
              >
                {currencies.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <span className="mt-1 block text-xs text-muted">
                A fixed amount only applies in its own currency.
              </span>
              {errors.currency && <p className="mt-1 text-xs text-warn">{errors.currency}</p>}
            </label>
          )}

          <label className="block text-xs text-muted">
            Minimum spend
            <input
              type="text"
              inputMode="decimal"
              value={minSubtotal}
              onChange={(e) => setMinSubtotal(e.target.value)}
              placeholder="0"
              className={`mt-1 ${FIELD}`}
            />
          </label>

          <label className="block text-xs text-muted">
            Total uses
            <input
              type="text"
              inputMode="numeric"
              value={usageLimit}
              onChange={(e) => setUsageLimit(e.target.value)}
              placeholder="unlimited"
              className={`mt-1 ${FIELD}`}
            />
          </label>

          <label className="block text-xs text-muted">
            Ends
            <input
              type="date"
              value={endsAt}
              onChange={(e) => setEndsAt(e.target.value)}
              className={`mt-1 ${FIELD}`}
            />
          </label>

          <div className="flex items-end">
            <button
              type="submit"
              disabled={pending}
              className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
            >
              {pending ? "Creating…" : "Create coupon"}
            </button>
          </div>
        </form>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold">
          {coupons.length} {coupons.length === 1 ? "coupon" : "coupons"}
        </h2>
        {coupons.length === 0 ? (
          <p className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center text-sm text-muted">
            No coupons yet.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line">
            <table className="w-full min-w-[36rem] text-sm">
              <thead className="bg-surface text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Code</th>
                  <th className="px-3 py-2 text-left font-medium">Discount</th>
                  <th className="px-3 py-2 text-left font-medium">Used</th>
                  <th className="px-3 py-2 text-left font-medium">State</th>
                </tr>
              </thead>
              <tbody>
                {coupons.map((coupon) => {
                  const reason = couponInactiveReason(coupon);
                  return (
                    <tr key={coupon.id} className="border-t border-line">
                      <td className="px-3 py-2 font-mono">{coupon.code}</td>
                      <td className="px-3 py-2">
                        {coupon.type === "percent" && `${coupon.value}%`}
                        {coupon.type === "fixed" && `${coupon.currency ?? ""} ${coupon.value}`}
                        {coupon.type === "free_shipping" && "Free shipping"}
                      </td>
                      <td className="px-3 py-2 tabular-nums">
                        {coupon.redemption_count}
                        {coupon.usage_limit !== null && ` / ${coupon.usage_limit}`}
                      </td>
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          onClick={() => toggle(coupon)}
                          disabled={busy === coupon.id}
                          className={`rounded-full border px-2 py-0.5 text-xs disabled:opacity-40 ${
                            reason ? "border-line text-muted" : "border-ok/50 text-ok"
                          }`}
                          title={coupon.is_active ? "Switch off" : "Switch on"}
                        >
                          {reason ?? "Working"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
