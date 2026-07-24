/** Gateway code -> display. Only bank_transfer is active in Plan-14; the others are
 * ready for Plan-14b so they render correctly the moment the API returns them. */
export interface PaymentLabel { name: string; note: string }
const LABELS: Record<string, PaymentLabel> = {
  bank_transfer: { name: "Bank transfer", note: "Pay by transfer — we confirm your order once the funds arrive." },
  paystack: { name: "Card / Paystack", note: "Pay securely with your card via Paystack." },
  flutterwave: { name: "Card / Flutterwave", note: "Pay securely with your card via Flutterwave." },
  paypal: { name: "PayPal", note: "Pay with your PayPal account." },
};
export function paymentLabel(gateway: string): PaymentLabel {
  return LABELS[gateway] ?? { name: gateway, note: "" };
}
