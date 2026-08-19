"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { PaymentMethodSwitch } from "@/components/checkout/PaymentMethodSwitch";
import { PaymentLauncher, type LaunchInfo } from "@/components/checkout/PaymentLauncher";
import { stashBankHandoff } from "@/lib/bank-handoff";

/** The pay-again island (Plan-38 gap fix; the FW-cert open item). Rendered on the
 * account order page and the confirmation page for an order still awaiting payment —
 * the two places a customer lands AFTER leaving checkout, where until now there was
 * no way back into collection ("Back to checkout" met an empty cart, because
 * placement converts the cart).
 *
 * All the machinery already existed: `POST /api/checkout/pay` re-opens the money leg
 * (certified in the FW run; guests ride the httpOnly guest-order cookie), and
 * PaymentMethodSwitch + PaymentLauncher own the pick/collect/verify loop. This
 * component only gives them a home outside the checkout session.
 *
 * The picker shows EVERY active method for the order's market (excludeCurrent=false)
 * — reached from an order page, retrying the same method is the most likely wish,
 * unlike the mid-checkout switcher where that method just failed. */
export function PayAgain({
  orderNumber,
  currentGateway,
  country,
  title = "Complete your payment",
  intro = "This order is awaiting payment. Pick a payment method to pay now — your items are reserved.",
}: {
  orderNumber: string;
  currentGateway: string;
  country: string;
  title?: string;
  intro?: string;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  // Set once /api/checkout/pay answers with an online-gateway envelope: the launcher
  // takes over collection (inline pop-up or redirect) and owns verify + routing.
  const [launch, setLaunch] = useState<LaunchInfo | null>(null);

  /** Switched to bank transfer: the instructions exist ONLY in this response, so
   * stash them for ConfirmationBankDetails and land on the confirmation page (a
   * refresh when we're already there — the server re-renders with the new latest
   * gateway, so the bank block appears). Same handoff ReviewStep uses. */
  function onBankDetails(number: string, data: Record<string, unknown>) {
    stashBankHandoff(number, data);
    router.replace(`/checkout/confirmation/${encodeURIComponent(number)}`);
    router.refresh();
  }

  if (launch) {
    return (
      <div className="rounded-[var(--radius-card)] border border-line bg-surface p-5">
        <h2 className="font-display text-lg">{title}</h2>
        <div className="mt-3">
          <PaymentLauncher launch={launch} />
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-surface p-5">
      <h2 className="font-display text-lg">{title}</h2>
      <p className="mt-2 text-sm text-muted">{intro}</p>
      {open ? (
        <div className="mt-4">
          <PaymentMethodSwitch
            orderNumber={orderNumber}
            currentGateway={currentGateway}
            country={country}
            excludeCurrent={false}
            onRelaunch={setLaunch}
            onBankDetails={onBankDetails}
          />
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="mt-4 rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm font-medium text-surface transition-colors hover:bg-accent-strong"
        >
          Pay now
        </button>
      )}
    </div>
  );
}
