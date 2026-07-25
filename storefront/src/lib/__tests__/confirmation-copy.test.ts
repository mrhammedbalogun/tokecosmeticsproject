import { describe, it, expect } from "vitest";
import { confirmationCopy } from "@/lib/confirmation-copy";

/** The confirmation page used to hardcode bank-transfer copy, because bank transfer was
 * the only method when it was written (Plan-14). Plan-14b switched the online gateways on
 * and nothing revisited this page, so a customer who had just paid by card was told to go
 * and make a bank transfer, and was shown a "Payment details" block pointing at transfer
 * instructions. Found driving the Paystack certification (order TC-100040). */
describe("confirmationCopy", () => {
  it("asks a bank-transfer customer to complete the transfer", () => {
    const copy = confirmationCopy({ gateway: "bank_transfer", status: "pending_payment" });

    expect(copy.showBankDetails).toBe(true);
    expect(copy.banner).toMatch(/complete your bank transfer/i);
  });

  it("tells a card customer their payment landed, and shows no transfer instructions", () => {
    const copy = confirmationCopy({ gateway: "paystack", status: "processing" });

    expect(copy.showBankDetails).toBe(false);
    expect(copy.banner).not.toMatch(/bank transfer/i);
    expect(copy.banner).toMatch(/payment/i);
  });

  it("does not claim payment landed while an online order is still unpaid", () => {
    // The webhook may still be in flight, or the attempt may have failed and be
    // retryable. Either way "we have your money" is the one thing we must not say.
    const copy = confirmationCopy({ gateway: "paystack", status: "pending_payment" });

    expect(copy.showBankDetails).toBe(false);
    expect(copy.banner).toMatch(/confirming/i);
  });

  it("treats every online gateway the same way", () => {
    for (const gateway of ["paystack", "flutterwave", "paypal"]) {
      expect(confirmationCopy({ gateway, status: "processing" }).showBankDetails).toBe(false);
    }
  });

  it("shows no payment instructions at all when the gateway is unknown", () => {
    // Legacy imported orders carry no Payment row, so the API reports "". Guessing wrong
    // here is what caused the bug, so guess neither way.
    const copy = confirmationCopy({ gateway: "", status: "processing" });

    expect(copy.showBankDetails).toBe(false);
    expect(copy.banner).not.toMatch(/bank transfer/i);
  });
});
