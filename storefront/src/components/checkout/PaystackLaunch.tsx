"use client";
import { useEffect, useRef } from "react";

interface Props {
  data: Record<string, unknown>;
  onGatewaySuccess: () => void; // money taken at the gateway; parent then verifies
  onGatewayAbort: () => void; // customer closed the pop-up / SDK error
}

/** Paystack inline pop-up. Uses the server-minted access_code (no public key needed).
 * The parent (PaymentLauncher) owns the verify + route step; this only drives the SDK.
 *
 * Every failure — a missing access code, a construction throw, or the SDK's own onError —
 * reports onGatewayAbort rather than rendering its own message, so the customer always
 * sees ONE retry surface (the launcher's) no matter how the pop-up failed. */
export function PaystackLaunch({ data, onGatewaySuccess, onGatewayAbort }: Props) {
  const accessCode = typeof data.access_code === "string" ? data.access_code : "";
  const opened = useRef(false);

  useEffect(() => {
    if (opened.current) return; // StrictMode double-invoke guard — open exactly once
    opened.current = true;
    if (!accessCode) {
      onGatewayAbort();
      return;
    }
    // Imported here, not at module scope: @paystack/inline-js touches `window` the
    // moment it's evaluated, which crashes the server render of every page that
    // (transitively) imports this file — /checkout 500s before the browser is involved.
    (async () => {
      try {
        const { default: PaystackPop } = await import("@paystack/inline-js");
        const popup = new PaystackPop();
        popup.resumeTransaction(accessCode, {
          onSuccess: () => onGatewaySuccess(),
          onCancel: () => onGatewayAbort(),
          onError: () => onGatewayAbort(),
        });
      } catch {
        onGatewayAbort();
      }
    })();
  }, [accessCode, onGatewaySuccess, onGatewayAbort]);

  return <p className="text-sm text-muted">Complete your payment in the pop-up…</p>;
}
