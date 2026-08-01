"use client";

/**
 * Bank accounts and per-country gateways (Plan-19b).
 *
 * ── THE BANK ACCOUNT IS THE HIGHEST-VALUE ROW IN THE SYSTEM ─────────────────────────
 *
 * `BankAccount`'s own docstring: "this row IS the payment page for that country". Bank
 * transfer is the only live method, so the number below is what every Nigerian customer
 * types into their banking app. Plan-16 Amendment 1 calls the payout account the
 * catastrophic-loss target, which is why `settings.manage` is Owner-only and why this
 * screen makes the current number legible rather than hiding it behind an edit click —
 * an operator should be able to eyeball what customers are being told, at a glance.
 *
 * Deleting an account is not offered: it would not disable bank transfer, it would make
 * `initiate()` fail with nothing for the customer to read.
 */
import { startTransition, useState } from "react";
import {
  saveBankAccountAction,
  setGatewayActiveAction,
} from "@/app/(shell)/settings/payments/actions";
import {
  marketsWithoutAnAccount,
  type BankAccountRow,
  type GatewayRow,
} from "@/lib/money-config";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export function PaymentsConfig({
  accounts,
  gateways,
}: {
  accounts: BankAccountRow[];
  gateways: GatewayRow[];
}) {
  const stranded = marketsWithoutAnAccount(gateways, accounts);

  return (
    <div className="space-y-8">
      {stranded.length > 0 && (
        <p
          className="rounded-[var(--radius-card)] border border-warn/40 bg-warn/5 p-3 text-sm text-warn"
          role="alert"
        >
          <strong>{stranded.join(", ")}</strong>{" "}
          {stranded.length === 1 ? "offers" : "offer"} bank transfer with no active account.
          Customers there reach checkout and cannot be told where to send money.
        </p>
      )}

      <section>
        <h2 className="text-sm font-semibold">Bank accounts</h2>
        <p className="mt-1 text-sm text-muted">
          What a customer paying by transfer is told. One per market.
        </p>
        <div className="mt-3 space-y-4">
          {accounts.length === 0 ? (
            <p className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center text-sm text-muted">
              No bank accounts yet.
            </p>
          ) : (
            accounts.map((account) => <AccountCard key={account.id} account={account} />)
          )}
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold">Payment methods by market</h2>
        <p className="mt-1 text-sm text-muted">
          Which methods appear at checkout. Turning one on makes it live immediately.
        </p>
        <GatewayTable gateways={gateways} />
      </section>
    </div>
  );
}

function AccountCard({ account }: { account: BankAccountRow }) {
  const [bankName, setBankName] = useState(account.bank_name);
  const [accountName, setAccountName] = useState(account.account_name);
  const [accountNumber, setAccountNumber] = useState(account.account_number);
  const [instructions, setInstructions] = useState(account.instructions);
  const [isActive, setIsActive] = useState(account.is_active);
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const numberChanged = accountNumber.trim() !== account.account_number;

  const save = () => {
    setPending(true);
    setSaved(false);
    setErrors({});
    setMessage(null);
    startTransition(async () => {
      const state = await saveBankAccountAction({
        id: account.id,
        bank_name: bankName,
        account_name: accountName,
        account_number: accountNumber,
        instructions,
        is_active: isActive,
      });
      setPending(false);
      setConfirming(false);
      if (state.savedAt) setSaved(true);
      setErrors(state.fieldErrors ?? {});
      setMessage(state.message ?? null);
    });
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        // CHANGING THE NUMBER IS CONFIRMED IN WORDS. Every other field is cosmetic; this
        // one redirects money, and a typo is not recoverable once a customer has paid.
        if (numberChanged && !confirming) {
          setConfirming(true);
          return;
        }
        save();
      }}
      className="rounded-[var(--radius-card)] border border-line p-4"
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-medium">
          {account.country_name} <span className="text-muted">({account.currency})</span>
        </h3>
        <label className="flex items-center gap-2 text-xs text-muted">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
            className="h-4 w-4 rounded border-line"
          />
          Offered at checkout
        </label>
      </div>

      {message && (
        <p className="mt-3 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
          {message}
        </p>
      )}
      {saved && !message && (
        <p className="mt-3 rounded border border-ok/30 bg-ok/10 p-2 text-sm text-ok" role="status">
          Saved.
        </p>
      )}

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="block text-xs text-muted">
          Bank
          <input
            type="text"
            value={bankName}
            onChange={(e) => setBankName(e.target.value)}
            className={`mt-1 ${FIELD}`}
          />
          {errors.bank_name && <p className="mt-1 text-xs text-warn">{errors.bank_name}</p>}
        </label>
        <label className="block text-xs text-muted">
          Account name
          <input
            type="text"
            value={accountName}
            onChange={(e) => setAccountName(e.target.value)}
            className={`mt-1 ${FIELD}`}
          />
        </label>
        <label className="block text-xs text-muted">
          Account number
          <input
            type="text"
            value={accountNumber}
            onChange={(e) => setAccountNumber(e.target.value)}
            className={`mt-1 font-mono ${FIELD}`}
          />
          {errors.account_number && (
            <p className="mt-1 text-xs text-warn">{errors.account_number}</p>
          )}
        </label>
      </div>

      <label className="mt-3 block text-xs text-muted">
        Instructions shown with the details
        <textarea
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          rows={2}
          className={`mt-1 ${FIELD}`}
        />
      </label>

      {confirming && numberChanged && (
        <div className="mt-3 rounded border border-warn/40 bg-warn/5 p-3" role="alert">
          <p className="text-sm font-medium text-warn">
            You are changing the account customers pay into.
          </p>
          <p className="mt-1 font-mono text-sm text-warn">
            {account.account_number} → {accountNumber.trim()}
          </p>
          <p className="mt-1 text-sm text-warn">
            Every new bank-transfer order will quote the new number. Money already sent to
            the old one is not affected.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="submit"
              disabled={pending}
              className="rounded bg-warn px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
            >
              {pending ? "Saving…" : "Change it"}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {!confirming && (
        <button
          type="submit"
          disabled={pending}
          className="mt-3 rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
        >
          {pending ? "Saving…" : "Save account"}
        </button>
      )}
    </form>
  );
}

function GatewayTable({ gateways }: { gateways: GatewayRow[] }) {
  const [busy, setBusy] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const toggle = (row: GatewayRow) => {
    setBusy(row.id);
    setMessage(null);
    startTransition(async () => {
      const state = await setGatewayActiveAction(row.id, !row.is_active);
      setBusy(null);
      setMessage(state.message ?? null);
    });
  };

  const byCountry = new Map<string, GatewayRow[]>();
  for (const row of gateways) {
    byCountry.set(row.country, [...(byCountry.get(row.country) ?? []), row]);
  }

  return (
    <div className="mt-3 space-y-3">
      {message && (
        <p className="rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
          {message}
        </p>
      )}
      {[...byCountry.entries()].map(([country, rows]) => (
        <div key={country} className="rounded-[var(--radius-card)] border border-line p-3">
          <h3 className="text-sm font-medium">{country}</h3>
          <ul className="mt-2 flex flex-wrap gap-2">
            {rows.map((row) => (
              <li key={row.id}>
                <button
                  type="button"
                  onClick={() => toggle(row)}
                  disabled={busy === row.id}
                  className={`rounded-full border px-3 py-1 text-xs disabled:opacity-40 ${
                    row.is_active
                      ? "border-ok/50 text-ok"
                      : "border-line text-muted hover:border-accent"
                  }`}
                  title={row.is_active ? "Live — click to switch off" : "Off — click to make live"}
                >
                  {row.gateway} · {row.is_active ? "on" : "off"}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
