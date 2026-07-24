/** Client-side helper: ask the BFF to re-verify a payment. Used by the inline pop-up
 * callbacks (Paystack/PayPal) and the Flutterwave return page. Never throws — every
 * failure resolves to { ok: false } so callers can show a calm retry/pending state. */
export interface VerifyOutcome {
  ok: boolean;
  orderNumber: string | null;
  orderStatus: string | null;
  paymentStatus: string | null;
}

export async function verifyPayment(reference: string): Promise<VerifyOutcome> {
  try {
    const res = await fetch("/api/checkout/verify", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ reference }),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok || !data) {
      return { ok: false, orderNumber: null, orderStatus: null, paymentStatus: null };
    }
    return {
      ok: true,
      orderNumber: data.order_number ?? null,
      orderStatus: data.order_status ?? null,
      paymentStatus: data.payment_status ?? null,
    };
  } catch {
    return { ok: false, orderNumber: null, orderStatus: null, paymentStatus: null };
  }
}
