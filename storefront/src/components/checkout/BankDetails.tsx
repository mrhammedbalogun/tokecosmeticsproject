"use client";
import { useState } from "react";
import { formatMoney, symbolFor } from "@/lib/country";
import type { BankDetailsData } from "@/lib/bank-handoff";

/** Presentational bank-transfer details card (Plan-14 Task 10). Renders exactly what
 * the server sent — never computes money itself. `data.display` is the primary
 * source (label -> value, server-ordered); if it's absent (older/unexpected payload
 * shape) fall back to the well-known bank_name/account_name/account_number fields so
 * the card still shows something useful instead of going blank. */
function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API can be unavailable (permissions, non-secure context) — the
      // value is still selectable text on the page, so failing silently is fine.
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label={`Copy ${value}`}
      className="ml-2 shrink-0 text-xs font-medium text-accent hover:text-accent-strong"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function BankDetails({
  data,
  amount,
  currency,
}: {
  data: BankDetailsData;
  amount?: string;
  currency?: string;
}) {
  const display =
    data.display ??
    (() => {
      const fallback: Record<string, string> = {};
      if (typeof data.bank_name === "string") fallback["Bank"] = data.bank_name;
      if (typeof data.account_name === "string") fallback["Account name"] = data.account_name;
      if (typeof data.account_number === "string") fallback["Account number"] = data.account_number;
      return fallback;
    })();
  const rows = Object.entries(display);

  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-surface p-5">
      <h2 className="font-display text-lg">Bank transfer details</h2>

      {amount && currency && (
        <p className="mt-3 text-sm">
          <span className="text-muted">Amount to transfer: </span>
          <span className="font-medium">{formatMoney(amount, currency, symbolFor(currency))}</span>
        </p>
      )}

      {rows.length > 0 && (
        <dl className="mt-4 space-y-2 border-t border-line pt-4 text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="flex items-center justify-between gap-2">
              <dt className="text-muted">{label}</dt>
              <dd className="flex items-center font-medium">
                <span>{value}</span>
                <CopyButton value={value} />
              </dd>
            </div>
          ))}
        </dl>
      )}

      {data.reference && (
        <p className="mt-4 rounded-[var(--radius-card)] bg-beige p-3 text-sm">
          <span className="text-muted">Payment reference — </span>
          <span className="font-medium">{data.reference}</span>
          <CopyButton value={data.reference} />
        </p>
      )}

      {data.instructions && <p className="mt-4 text-sm text-muted">{data.instructions}</p>}
    </div>
  );
}
