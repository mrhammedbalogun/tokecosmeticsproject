"use client";
import { useEffect, useRef } from "react";
import PaystackPop from "@paystack/inline-js";

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
    try {
      const popup = new PaystackPop();
      popup.resumeTransaction(accessCode, {
        onSuccess: () => onGatewaySuccess(),
        onCancel: () => onGatewayAbort(),
        onError: () => onGatewayAbort(),
      });
    } catch {
      onGatewayAbort();
    }
  }, [accessCode, onGatewaySuccess, onGatewayAbort]);

  return <p className="text-sm text-muted">Complete your payment in the pop-up…</p>;
}
