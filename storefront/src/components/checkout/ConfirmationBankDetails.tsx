"use client";
import { useState } from "react";
import { readBankHandoff } from "@/lib/bank-handoff";
import { BankDetails } from "@/components/checkout/BankDetails";

/** Client island on the confirmation page (Plan-14 Task 11). The bank details only
 * ever exist in the place-order response — there is no endpoint to fetch them again —
 * so ReviewStep stashed them in sessionStorage keyed by order number right after the
 * 201, and this reads them back once. Lazy useState initializer (not an effect):
 * sessionStorage is client-only and this component only ever renders on the client,
 * so there's no hydration-mismatch concern, and it sidesteps the
 * react-hooks/set-state-in-effect rule entirely. A later revisit of this URL (handoff
 * gone — sessionStorage was cleared, tab closed, or a different device via a shared
 * link) falls back to a muted "contact support" note rather than crashing or showing
 * nothing. */
export function ConfirmationBankDetails({
  number,
  amount,
  currency,
}: {
  number: string;
  amount?: string;
  currency?: string;
}) {
  const [data] = useState(() => readBankHandoff(number));

  if (!data) {
    return (
      <div className="rounded-[var(--radius-card)] border border-line bg-surface p-5">
        <h2 className="font-display text-lg">Payment details</h2>
        <p className="mt-3 text-sm text-muted">
          Your bank transfer details were shown at checkout and emailed to you. Need
          them again? Contact support with your order number.
        </p>
      </div>
    );
  }

  return (
    <div>
      <h2 className="font-display text-lg">Payment details</h2>
      <div className="mt-3">
        <BankDetails data={data} amount={amount} currency={currency} />
      </div>
    </div>
  );
}
