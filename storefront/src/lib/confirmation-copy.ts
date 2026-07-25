/** What the confirmation page should say about money, given how the order was paid.
 *
 * Kept as a pure function rather than inlined in the page because the page is an async
 * server component: this is the part with the branching, and this way it is testable.
 *
 * The bug this fixes: the page hardcoded bank-transfer copy — correct in Plan-14, when
 * bank transfer was the only method, and wrong the moment Plan-14b switched the online
 * gateways on. A customer who had just paid by card was told to go and make a transfer.
 */
export interface ConfirmationCopy {
  /** The banner under the heading. */
  banner: string;
  /** Whether to render the bank account/reference block. */
  showBankDetails: boolean;
}

/** Gateways whose money moves at checkout. bank_transfer is the manual one; "" means the
 * order has no payment row at all (legacy import) and we say nothing either way, because
 * guessing is exactly what caused the bug. */
const MANUAL = "bank_transfer";

export function confirmationCopy({
  gateway,
  status,
}: {
  gateway: string;
  status: string;
}): ConfirmationCopy {
  if (gateway === MANUAL) {
    return {
      banner:
        "Your order is reserved. Complete your bank transfer using the details below; " +
        "we'll confirm and dispatch once payment arrives.",
      showBankDetails: true,
    };
  }

  if (!gateway) {
    return { banner: "Your order is confirmed. We'll email you when it ships.", showBankDetails: false };
  }

  // Online gateway. `processing` is the only status that means the money actually landed
  // and was reconciled against the order total — anything else (a webhook still in
  // flight, a failed attempt awaiting retry) must NOT be reported as paid.
  return status === "processing"
    ? {
        banner: "We've received your payment. We'll email you when your order ships.",
        showBankDetails: false,
      }
    : {
        banner:
          "We're confirming your payment — you'll get an email as soon as it clears.",
        showBankDetails: false,
      };
}
