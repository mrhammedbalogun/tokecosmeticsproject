"use client";
import { useEffect, useState } from "react";
import { paymentLabel } from "@/lib/payment-labels";
import type { LaunchInfo } from "@/components/checkout/PaymentLauncher";
import type { PaymentMethod } from "@/lib/checkout";

interface Props {
  orderNumber: string;
  currentGateway: string;
  /** A fresh online-gateway attempt to collect money with. */
  onRelaunch: (launch: LaunchInfo) => void;
  /** A bank-transfer switch: instructions to hand off to the confirmation page. */
  onBankDetails: (orderNumber: string, data: Record<string, unknown>) => void;
  /** Default true (the mid-checkout switcher: the method that just failed is not
   * worth offering back). PayAgain passes false — reached from an order page later,
   * retrying the SAME method is a perfectly good first choice. */
  excludeCurrent?: boolean;
  /** The ORDER's market, when the caller knows it (order pages do). Without it the
   * methods list follows the browsing-country cookie, which can drift from the
   * order's market if the shopper switched countries since placing — the backend
   * would refuse the mismatched gateway anyway, but listing it is a dead button. */
  country?: string;
}

interface FetchResult {
  methods: PaymentMethod[];
  error: string | null;
}

/** Offered when an online payment fails: pick a different method for an order that has
 * ALREADY been placed. The order keeps its lines, totals and stock — only the money leg
 * is re-opened (`POST /api/checkout/pay`), so nothing here re-prices anything. */
export function PaymentMethodSwitch({
  orderNumber, currentGateway, onRelaunch, onBankDetails,
  excludeCurrent = true, country,
}: Props) {
  const [result, setResult] = useState<FetchResult | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(
          country
            ? `/api/checkout/payment-methods?country=${encodeURIComponent(country)}`
            : "/api/checkout/payment-methods"
        );
        const data = await res.json().catch(() => null);
        if (cancelled) return;
        if (!res.ok || !Array.isArray(data)) {
          setResult({ methods: [], error: "Couldn't load payment methods — please try again." });
          return;
        }
        setResult({ methods: data as PaymentMethod[], error: null });
      } catch {
        if (!cancelled) {
          setResult({ methods: [], error: "Couldn't load payment methods — please try again." });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [country]);

  async function choose(gateway: string) {
    if (busy) return;
    setBusy(gateway);
    setError("");
    try {
      const res = await fetch("/api/checkout/pay", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ order_number: orderNumber, payment_gateway: gateway }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data?.payment) {
        setError(
          data?.error === "order_not_payable"
            ? "This order can no longer be paid here — please contact us and we'll help."
            : "We couldn't switch payment method just now. Please try again."
        );
        return;
      }
      const payment = data.payment;
      if (payment.action === "bank_details") {
        onBankDetails(data.order_number, payment.data ?? {});
        return;
      }
      onRelaunch({
        gateway: payment.gateway,
        reference: payment.reference,
        orderNumber: data.order_number,
        data: payment.data ?? {},
      });
    } catch {
      setError("We couldn't switch payment method just now. Please try again.");
    } finally {
      setBusy("");
    }
  }

  if (result === null) return <p className="text-sm text-muted">Loading payment methods…</p>;

  // Mid-checkout, the method that just failed is not worth offering back as an
  // alternative; from an order page (excludeCurrent=false) every active method stands.
  const others = excludeCurrent
    ? result.methods.filter((m) => m.gateway !== currentGateway)
    : result.methods;

  return (
    <div className="space-y-3">
      {result.error && (
        <p role="alert" className="text-sm text-red-700">
          {result.error}
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      )}
      {!result.error && others.length === 0 && (
        <p className="text-sm text-muted">
          There&apos;s no other payment method available for your region — please contact us and
          we&apos;ll sort it out.
        </p>
      )}
      {others.map((method) => {
        const label = paymentLabel(method.gateway);
        return (
          <button
            key={method.gateway}
            type="button"
            onClick={() => choose(method.gateway)}
            disabled={Boolean(busy)}
            className="block w-full rounded-[var(--radius-card)] border border-line p-4 text-left text-sm transition-colors hover:border-accent/60 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span className="font-medium">
              {busy === method.gateway ? "Starting…" : label.name}
            </span>
            {label.note && <span className="mt-1 block text-muted">{label.note}</span>}
          </button>
        );
      })}
    </div>
  );
}
