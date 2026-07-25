"use client";
import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { verifyPayment } from "@/lib/payment-verify";
import { stashBankHandoff } from "@/lib/bank-handoff";
import { PaystackLaunch } from "@/components/checkout/PaystackLaunch";
import { PaypalLaunch } from "@/components/checkout/PaypalLaunch";
import { FlutterwaveLaunch } from "@/components/checkout/FlutterwaveLaunch";
import { PaymentMethodSwitch } from "@/components/checkout/PaymentMethodSwitch";

export interface LaunchInfo {
  gateway: string;
  reference: string; // = payment.gateway_reference (verify keys on it)
  orderNumber: string; // the order already exists — name it if collection fails
  data: Record<string, unknown>; // payment.data from the 201
}

type Phase = "collecting" | "verifying" | "pending" | "failed" | "switching";

/** Owns the money-collection UI once an order is placed with an online gateway. Delegates
 * SDK specifics to the per-gateway child, then verifies server-side and routes. Every
 * path reaches a terminal state — success, a retry prompt, or a calm "we'll email you" —
 * so the customer is never left on a spinner after paying. */
export function PaymentLauncher({ launch: initialLaunch }: { launch: LaunchInfo }) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("collecting");
  // A method switch replaces the launch we are collecting against: the backend opened a
  // NEW payment attempt on the chosen gateway, with its own reference and SDK material.
  const [launch, setLaunch] = useState<LaunchInfo>(initialLaunch);
  // Bumped on retry and used as the child's key, so the SDK child remounts and re-opens
  // (its own open-once guard is per-mount).
  const [attempt, setAttempt] = useState(0);
  // A gateway can report success more than once (SDK retries, double callback). Verify is
  // idempotent server-side, but firing it twice would race two navigations.
  const verified = useRef(false);

  const onGatewaySuccess = useCallback(async () => {
    if (verified.current) return;
    verified.current = true;
    setPhase("verifying");
    const out = await verifyPayment(launch.reference);
    if (out.ok && out.paymentStatus === "succeeded" && out.orderNumber) {
      router.replace(`/checkout/confirmation/${out.orderNumber}`);
      return;
    }
    // Money may be in flight (the webhook will reconcile) or genuinely not taken. Either
    // way, don't spin: show a calm terminal state. The confirmation email lands when it
    // clears. Do NOT claim failure here — we can't tell the two apart from one verify.
    setPhase("pending");
  }, [launch.reference, router]);

  const onGatewayAbort = useCallback(() => setPhase("failed"), []);

  function retry() {
    verified.current = false;
    setAttempt((n) => n + 1);
    setPhase("collecting");
  }

  /** A switch produced a brand-new attempt — collect against that one from now on. */
  function onRelaunch(next: LaunchInfo) {
    verified.current = false;
    setLaunch(next);
    setAttempt((n) => n + 1);
    setPhase("collecting");
  }

  /** Switched to bank transfer: nothing to collect on-page. Hand the instructions to the
   * confirmation page the same way ReviewStep does — they live ONLY in this response. */
  function onBankDetails(orderNumber: string, data: Record<string, unknown>) {
    stashBankHandoff(orderNumber, data);
    router.replace(`/checkout/confirmation/${orderNumber}`);
  }

  if (phase === "switching") {
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted">Choose a different way to pay for this order.</p>
        <PaymentMethodSwitch
          orderNumber={launch.orderNumber}
          currentGateway={launch.gateway}
          onRelaunch={onRelaunch}
          onBankDetails={onBankDetails}
        />
        <button type="button" onClick={retry} className="text-sm underline">
          Back
        </button>
      </div>
    );
  }

  if (phase === "failed") {
    return (
      <div className="space-y-3">
        <p role="alert" className="text-sm text-red-700">
          Your payment didn&apos;t go through.
        </p>
        {/* Placing the order already converted the cart, so there is no bag to go back
            to — both routes out have to work on THIS order. Retry re-opens the same
            attempt (the Paystack access code / PayPal order id stays valid); the switch
            asks the backend to open a new attempt on another gateway. Naming the order
            matters: it exists and is waiting, and saying so stops the customer fearing
            they have lost it (or re-ordering). */}
        <p className="text-sm text-muted">
          Your order <span className="font-medium text-foreground">{launch.orderNumber}</span> is
          saved — you can try again or pay a different way.
        </p>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={retry}
            className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm font-medium text-surface transition-colors hover:bg-accent-strong"
          >
            Try again
          </button>
          <button
            type="button"
            onClick={() => setPhase("switching")}
            className="rounded-[var(--radius-card)] border border-line px-4 py-2 text-sm font-medium transition-colors hover:border-accent/60"
          >
            Choose another method
          </button>
        </div>
      </div>
    );
  }
  if (phase === "pending") {
    return (
      <p className="text-sm text-muted">
        We&apos;re confirming your payment — you&apos;ll get an email as soon as it clears.
      </p>
    );
  }
  if (phase === "verifying") {
    return <p className="text-sm text-muted">Confirming your payment…</p>;
  }

  // phase === "collecting"
  switch (launch.gateway) {
    case "paystack":
      return (
        <PaystackLaunch
          key={attempt}
          data={launch.data}
          onGatewaySuccess={onGatewaySuccess}
          onGatewayAbort={onGatewayAbort}
        />
      );
    case "paypal":
      return (
        <PaypalLaunch
          key={attempt}
          data={launch.data}
          onGatewaySuccess={onGatewaySuccess}
          onGatewayAbort={onGatewayAbort}
        />
      );
    case "flutterwave":
      return <FlutterwaveLaunch key={attempt} data={launch.data} />;
    default:
      return (
        <p role="alert" className="text-sm text-red-700">
          That payment method isn&apos;t available right now. Please choose another.
        </p>
      );
  }
}
