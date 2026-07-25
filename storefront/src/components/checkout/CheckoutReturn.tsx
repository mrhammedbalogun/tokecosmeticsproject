"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { verifyPayment } from "@/lib/payment-verify";

type State = "polling" | "failed" | "pending" | "missing";

const DEFAULT_MAX_POLLS = 5;
const DEFAULT_POLL_DELAY_MS = 3000;

/** Where Flutterwave redirects back to. Bounded polling → always a terminal state:
 * confirmation, a retry prompt, or "we'll email you". Never an infinite spinner.
 *
 * Polling exists because the hosted page can return the customer before the gateway has
 * finished settling; the webhook reconciles anything still open when we stop asking. */
export function CheckoutReturn({
  reference,
  maxPolls = DEFAULT_MAX_POLLS,
  pollDelayMs = DEFAULT_POLL_DELAY_MS,
}: {
  reference: string;
  maxPolls?: number;
  pollDelayMs?: number;
}) {
  const router = useRouter();
  // Derived at mount, never set from inside the effect for the missing case — a bare
  // return URL is knowable at render time (react-hooks/set-state-in-effect).
  const [state, setState] = useState<State>(reference ? "polling" : "missing");
  const started = useRef(false);

  useEffect(() => {
    if (!reference || started.current) return;
    started.current = true;
    let cancelled = false;

    (async () => {
      for (let attempt = 0; attempt < maxPolls; attempt++) {
        const out = await verifyPayment(reference);
        if (cancelled) return;
        if (out.ok && out.paymentStatus === "succeeded" && out.orderNumber) {
          router.replace(`/checkout/confirmation/${out.orderNumber}`);
          return;
        }
        if (out.ok && (out.paymentStatus === "failed" || out.paymentStatus === "cancelled")) {
          setState("failed");
          return;
        }
        if (attempt < maxPolls - 1 && pollDelayMs > 0) {
          await new Promise((r) => setTimeout(r, pollDelayMs));
          if (cancelled) return;
        }
      }
      if (!cancelled) setState("pending"); // still pending after the last poll
    })();

    return () => {
      cancelled = true;
    };
  }, [reference, maxPolls, pollDelayMs, router]);

  if (state === "missing") {
    return (
      <p role="alert" className="text-sm text-red-700">
        We couldn&apos;t find your payment. Please return to checkout and try again.
      </p>
    );
  }
  if (state === "failed") {
    return (
      <div className="space-y-2">
        <p role="alert" className="text-sm text-red-700">
          Your payment didn&apos;t go through. You can try again or choose another method.
        </p>
        <a href="/checkout" className="text-sm underline">
          Back to checkout
        </a>
      </div>
    );
  }
  if (state === "pending") {
    return (
      <p className="text-sm text-muted">
        We&apos;re confirming your payment — you&apos;ll get an email as soon as it clears.
      </p>
    );
  }
  return <p className="text-sm text-muted">Confirming your payment…</p>;
}
