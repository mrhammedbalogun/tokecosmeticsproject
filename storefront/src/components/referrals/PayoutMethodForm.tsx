"use client";

/**
 * Where a referrer's money is sent.
 *
 * The stored account number is NEVER sent back to the browser — the API publishes only
 * "•••• 6789" — so the number field always starts EMPTY, even when an account is already
 * saved. That looks like a bug until you see the alternative: prefilling it would mean
 * either shipping the full number to every render of this page, or prefilling bullets
 * that get submitted verbatim the first time somebody edits the bank name and saves.
 * The saved account is shown above the form instead, masked, so nobody is left guessing
 * what is on file.
 *
 * Every save emails the account holder (backend), which is what makes an account
 * takeover redirecting payouts noisy rather than silent. The form says so, because a
 * customer who gets that email should recognise it.
 */
import { useActionState, useState } from "react";
import type {
  PayoutMethodState,
} from "@/app/(shop)/account/referrals/actions";
import type { PayoutMethod } from "@/lib/referrals";

const ERROR_ID = "payout-method-error";

const inputClass =
  "w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm " +
  "focus:outline-none focus:ring-2 focus:ring-accent/40";

/** Extra fields a market needs beyond bank + name + number. Keyed by currency so a
 * referrer entering GBP details is asked for a sort code and a naira account holder is
 * not. Empty for NGN: a NUBAN plus the bank is the whole address. */
const EXTRA_FIELDS: Record<string, { name: string; label: string }[]> = {
  GBP: [{ name: "sort_code", label: "Sort code" }],
  USD: [{ name: "routing_number", label: "Routing number" }],
  CAD: [
    { name: "routing_number", label: "Transit & institution number" },
  ],
};

export function PayoutMethodForm({
  currencies,
  existing,
  action,
  defaultCurrency,
}: {
  /** Currencies the shop can actually pay out — the referrer's own wallets. */
  currencies: { code: string; label: string }[];
  existing: PayoutMethod[];
  action: (state: PayoutMethodState, formData: FormData) => Promise<PayoutMethodState>;
  defaultCurrency: string;
}) {
  const [state, formAction, pending] = useActionState(action, {});
  const [currency, setCurrency] = useState(defaultCurrency);
  const saved = existing.find((m) => m.currency === currency);
  const extras = EXTRA_FIELDS[currency] ?? [];

  return (
    <form action={formAction} className="max-w-md space-y-4">
      <div aria-live="polite">
        {state.error && (
          <p id={ERROR_ID} role="alert" className="text-sm text-red-700">
            {state.error}
          </p>
        )}
        {state.saved && !state.error && (
          <p className="text-sm text-accent-strong">
            Bank details saved. We&rsquo;ve emailed you to confirm the change.
          </p>
        )}
      </div>

      {currencies.length > 1 && (
        <div>
          <label htmlFor="payout-currency" className="mb-1 block text-sm font-medium">
            Currency
          </label>
          <select
            id="payout-currency"
            name="currency"
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            className={inputClass}
          >
            {currencies.map((c) => (
              <option key={c.code} value={c.code}>
                {c.label}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-muted">
            Each currency is paid to its own account — we don&rsquo;t convert between them.
          </p>
        </div>
      )}
      {currencies.length === 1 && <input type="hidden" name="currency" value={currency} />}

      {saved && (
        <div className="rounded-[var(--radius-card)] bg-beige p-4 text-sm">
          <p className="font-medium">Currently on file</p>
          <p className="mt-1 text-muted">
            {saved.bank_name} · {saved.account_name} ·{" "}
            <span className="font-mono">{saved.account_number_masked}</span>
          </p>
        </div>
      )}

      <div>
        <label htmlFor="payout-bank" className="mb-1 block text-sm font-medium">
          Bank name
        </label>
        <input
          id="payout-bank"
          name="bank_name"
          type="text"
          required
          defaultValue={saved?.bank_name ?? ""}
          autoComplete="off"
          className={inputClass}
          aria-describedby={state.error ? ERROR_ID : undefined}
        />
      </div>

      <div>
        <label htmlFor="payout-account-name" className="mb-1 block text-sm font-medium">
          Account name
        </label>
        <input
          id="payout-account-name"
          name="account_name"
          type="text"
          required
          defaultValue={saved?.account_name ?? ""}
          autoComplete="off"
          className={inputClass}
        />
        <p className="mt-1 text-xs text-muted">
          Exactly as it appears on your bank account.
        </p>
      </div>

      <div>
        <label htmlFor="payout-account-number" className="mb-1 block text-sm font-medium">
          Account number
        </label>
        <input
          id="payout-account-number"
          name="account_number"
          type="text"
          required
          // No defaultValue, ever — see the file docstring.
          placeholder={saved ? "Re-enter to change" : ""}
          inputMode="numeric"
          autoComplete="off"
          className={inputClass}
        />
      </div>

      {extras.map((extra) => (
        <div key={extra.name}>
          <label htmlFor={`payout-${extra.name}`} className="mb-1 block text-sm font-medium">
            {extra.label}
          </label>
          <input
            id={`payout-${extra.name}`}
            name={extra.name}
            type="text"
            autoComplete="off"
            className={inputClass}
          />
        </div>
      ))}

      <button
        type="submit"
        disabled={pending}
        className="rounded-[var(--radius-card)] bg-accent px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
      >
        {pending ? "Saving…" : saved ? "Update bank details" : "Save bank details"}
      </button>

      <p className="text-xs text-muted">
        We email you whenever these details change, so you&rsquo;d know if someone else
        changed them.
      </p>
    </form>
  );
}
