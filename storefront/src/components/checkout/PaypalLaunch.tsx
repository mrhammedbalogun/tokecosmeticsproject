"use client";
import { useEffect } from "react";
import { PayPalScriptProvider, PayPalButtons } from "@paypal/react-paypal-js";

interface Props {
  data: Record<string, unknown>;
  onGatewaySuccess: () => void;
  onGatewayAbort: () => void;
}

/** PayPal inline Buttons. createOrder returns the SERVER-created order id (from
 * payment.data.order_id) — the amount is fixed server-side, never sent from the client.
 * onApprove hands off to the parent's verify step, which captures + confirms.
 *
 * The SDK script is loaded PER CURRENCY, so it must be keyed to the order's own currency
 * (payment.data.currency, set by the PayPal adapter): loading USD and then approving a
 * GBP order fails at the buyer's click. USD is only a last-resort fallback. */
export function PaypalLaunch({ data, onGatewaySuccess, onGatewayAbort }: Props) {
  const orderId = typeof data.order_id === "string" ? data.order_id : "";
  const currency = typeof data.currency === "string" && data.currency ? data.currency : "USD";
  const clientId = process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID ?? "";
  const unavailable = !clientId || !orderId;

  // Misconfiguration (no client id) or a malformed response (no order id) means we can
  // never collect here. Report it as an abort so the customer gets the launcher's single
  // retry surface instead of a dead end — same contract as PaystackLaunch.
  useEffect(() => {
    if (unavailable) onGatewayAbort();
  }, [unavailable, onGatewayAbort]);

  if (unavailable) return null;

  return (
    <PayPalScriptProvider options={{ clientId, currency, intent: "capture" }}>
      <PayPalButtons
        createOrder={() => Promise.resolve(orderId)}
        onApprove={() => {
          onGatewaySuccess();
          return Promise.resolve();
        }}
        onCancel={() => onGatewayAbort()}
        onError={() => onGatewayAbort()}
      />
    </PayPalScriptProvider>
  );
}
