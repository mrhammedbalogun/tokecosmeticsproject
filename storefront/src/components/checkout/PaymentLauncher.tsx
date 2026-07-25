"use client";
import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { verifyPayment } from "@/lib/payment-verify";
import { PaystackLaunch } from "@/components/checkout/PaystackLaunch";
import { PaypalLaunch } from "@/components/checkout/PaypalLaunch";
import { FlutterwaveLaunch } from "@/components/checkout/FlutterwaveLaunch";

export interface LaunchInfo {
  gateway: string;
  reference: string; // = payment.gateway_reference (verify keys on it)
  data: Record<string, unknown>; // payment.data from the 201
}

type Phase = "collecting" | "verifying" | "pending" | "failed";

/** Owns the money-collection UI once an order is placed with an online gateway. Delegates
 * SDK specifics to the per-gateway child, then verifies server-side and routes. Every
 * path reaches a terminal state — success, a retry prompt, or a calm "we'll email you" —
 * so the customer is never left on a spinner after paying. */
export function PaymentLauncher({ launch }: { launch: LaunchInfo }) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("collecting");
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

  if (phase === "failed") {
    return (
      <div className="space-y-2">
        <p role="alert" className="text-sm text-red-700">
          Your payment didn&apos;t go through. You can try again or choose another method.
        </p>
        <a href="/checkout" className="text-sm underline">
          Choose another method
        </a>
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
          data={launch.data}
          onGatewaySuccess={onGatewaySuccess}
          onGatewayAbort={onGatewayAbort}
        />
      );
    case "paypal":
      return (
        <PaypalLaunch
          data={launch.data}
          onGatewaySuccess={onGatewaySuccess}
          onGatewayAbort={onGatewayAbort}
        />
      );
    case "flutterwave":
      return <FlutterwaveLaunch data={launch.data} />;
    default:
      return (
        <p role="alert" className="text-sm text-red-700">
          That payment method isn&apos;t available right now. Please choose another.
        </p>
      );
  }
}
