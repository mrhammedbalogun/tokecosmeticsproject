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
  addGatewayAction,
  createBankAccountAction,
  removeGatewayAction,
  reorderGatewaysAction,
  saveBankAccountAction,
  setGatewayActiveAction,
} from "@/app/(shell)/settings/payments/actions";
import {
  addableGateways,
  gatewayObstacle,
  marketsAddableForAccount,
  marketsWithoutAnAccount,
  nextSortOrder,
  type BankAccountRow,
  type GatewayCatalogEntry,
  type GatewayRow,
} from "@/lib/money-config";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export function PaymentsConfig({
  accounts,
  gateways,
  catalog,
}: {
  accounts: BankAccountRow[];
  gateways: GatewayRow[];
  catalog: GatewayCatalogEntry[];
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
          {accounts.length === 0 && (
            <p className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center text-sm text-muted">
              No bank accounts yet.
            </p>
          )}
          {accounts.map((account) => (
            <AccountCard key={account.id} account={account} />
          ))}
          <AddAccountCard markets={marketsAddableForAccount(gateways, accounts)} />
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold">Payment methods by market</h2>
        <p className="mt-1 text-sm text-muted">
          Which methods appear at checkout, and in what order. Turning one on makes it
          live immediately — unless a warning says why it would stay hidden.
        </p>
        <GatewayTable gateways={gateways} catalog={catalog} />
      </section>
    </div>
  );
}

/** The extra display rows a market's wire needs beyond bank/name/number — sort code
 * (GB), routing number (US), IBAN/SWIFT. Labels are shown to the customer exactly as
 * typed (capitals preserved: write `IBAN`, not `iban`). */
function ExtraFieldsEditor({
  extra,
  onChange,
  error,
}: {
  extra: [string, string][];
  onChange: (next: [string, string][]) => void;
  error?: string;
}) {
  const set = (index: number, part: 0 | 1, value: string) => {
    onChange(extra.map((row, i) => (i === index ? ((part === 0 ? [value, row[1]] : [row[0], value]) as [string, string]) : row)));
  };
  return (
    <div className="mt-3">
      <p className="text-xs text-muted">
        Extra details shown with the account (e.g. Sort code, IBAN, SWIFT). Labels appear
        to the customer exactly as typed.
      </p>
      {extra.map(([label, value], index) => (
        <div key={index} className="mt-2 flex items-center gap-2">
          <input
            type="text"
            value={label}
            onChange={(e) => set(index, 0, e.target.value)}
            placeholder="Label (e.g. Sort code)"
            aria-label={`Extra detail ${index + 1} label`}
            className={`${FIELD} max-w-[14rem]`}
          />
          <input
            type="text"
            value={value}
            onChange={(e) => set(index, 1, e.target.value)}
            placeholder="Value"
            aria-label={`Extra detail ${index + 1} value`}
            className={`font-mono ${FIELD}`}
          />
          <button
            type="button"
            onClick={() => onChange(extra.filter((_, i) => i !== index))}
            aria-label={`Remove extra detail ${index + 1}`}
            className="shrink-0 text-xs text-muted hover:text-warn"
          >
            Remove
          </button>
        </div>
      ))}
      {error && <p className="mt-1 text-xs text-warn">{error}</p>}
      <button
        type="button"
        onClick={() => onChange([...extra, ["", ""]])}
        className="mt-2 text-xs text-accent hover:underline"
      >
        + Add a detail
      </button>
    </div>
  );
}

function AccountCard({ account }: { account: BankAccountRow }) {
  const [bankName, setBankName] = useState(account.bank_name);
  const [accountName, setAccountName] = useState(account.account_name);
  const [accountNumber, setAccountNumber] = useState(account.account_number);
  const [extra, setExtra] = useState<[string, string][]>(Object.entries(account.extra));
  const [description, setDescription] = useState(account.description);
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
        extra,
        description,
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

      <ExtraFieldsEditor extra={extra} onChange={setExtra} error={errors.extra} />

      <label className="mt-3 block text-xs text-muted">
        Description shown at checkout, while choosing how to pay
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          placeholder="e.g. Pay by transfer — we confirm your order once the funds arrive."
          className={`mt-1 ${FIELD}`}
        />
      </label>

      <label className="mt-3 block text-xs text-muted">
        Instructions shown with the details, after the order is placed
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

/** Give a market its account — the missing half of "enable bank transfer here". Only
 * markets with no row at all are offered (one account per market); existing accounts
 * are edited in place above. */
function AddAccountCard({
  markets,
}: {
  markets: { code: string; name: string; currency: string }[];
}) {
  const [country, setCountry] = useState("");
  const [bankName, setBankName] = useState("");
  const [accountName, setAccountName] = useState("");
  const [accountNumber, setAccountNumber] = useState("");
  const [extra, setExtra] = useState<[string, string][]>([]);
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");
  const [pending, setPending] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);

  if (markets.length === 0) return null;
  const market = markets.find((m) => m.code === country);

  const create = () => {
    if (!market) return;
    setPending(true);
    setErrors({});
    setMessage(null);
    startTransition(async () => {
      const state = await createBankAccountAction({
        country: market.code,
        currency: market.currency,
        bank_name: bankName,
        account_name: accountName,
        account_number: accountNumber,
        extra,
        description,
        instructions,
        // Live immediately: entering details for a stranded market IS the fix for the
        // "on but hidden" warning. The gateway toggle above stays the offer switch.
        is_active: true,
      });
      setPending(false);
      if (state.savedAt) {
        setCountry("");
        setBankName("");
        setAccountName("");
        setAccountNumber("");
        setExtra([]);
        setDescription("");
        setInstructions("");
      }
      setErrors(state.fieldErrors ?? {});
      setMessage(state.message ?? null);
    });
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        create();
      }}
      className="rounded-[var(--radius-card)] border border-dashed border-line p-4"
    >
      <h3 className="text-sm font-medium">Add a bank account</h3>
      <div className="mt-2 flex items-center gap-2">
        <label className="sr-only" htmlFor="add-account-market">
          Market
        </label>
        <select
          id="add-account-market"
          value={country}
          onChange={(e) => setCountry(e.target.value)}
          className={`${FIELD} max-w-xs`}
        >
          <option value="">Choose a market…</option>
          {markets.map((m) => (
            <option key={m.code} value={m.code}>
              {m.name} ({m.code} · {m.currency})
            </option>
          ))}
        </select>
      </div>

      {market && (
        <>
          {message && (
            <p
              className="mt-3 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn"
              role="alert"
            >
              {message}
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

          <ExtraFieldsEditor extra={extra} onChange={setExtra} error={errors.extra} />

          <label className="mt-3 block text-xs text-muted">
            Description shown at checkout, while choosing how to pay
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="e.g. Pay by transfer — we confirm your order once the funds arrive."
              className={`mt-1 ${FIELD}`}
            />
          </label>

          <label className="mt-3 block text-xs text-muted">
            Instructions shown with the details, after the order is placed
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              rows={2}
              placeholder="e.g. Use your order number as the transfer reference."
              className={`mt-1 ${FIELD}`}
            />
          </label>

          <button
            type="submit"
            disabled={pending}
            className="mt-3 rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            {pending ? "Creating…" : `Create ${market.code} account`}
          </button>
          <p className="mt-2 text-xs text-muted">
            Customers in {market.name} start seeing these details as soon as bank transfer
            is switched on for that market.
          </p>
        </>
      )}
    </form>
  );
}

function GatewayTable({
  gateways,
  catalog,
}: {
  gateways: GatewayRow[];
  catalog: GatewayCatalogEntry[];
}) {
  const [busy, setBusy] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const run = (id: number | null, act: () => Promise<{ message?: string | null }>) => {
    setBusy(id);
    setMessage(null);
    startTransition(async () => {
      const state = await act();
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
        <MarketCard
          key={country}
          country={country}
          rows={[...rows].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)}
          catalog={catalog}
          busy={busy}
          run={run}
        />
      ))}
    </div>
  );
}

function MarketCard({
  country,
  rows,
  catalog,
  busy,
  run,
}: {
  country: string;
  rows: GatewayRow[];
  catalog: GatewayCatalogEntry[];
  busy: number | null;
  run: (id: number | null, act: () => Promise<{ message?: string | null }>) => void;
}) {
  const [adding, setAdding] = useState("");
  const [removing, setRemoving] = useState<number | null>(null);
  const addable = addableGateways(catalog, rows);
  const currency = rows[0]?.country_currency ?? "";

  // Checkout shows the menu in sort order — moving a row means renumbering the market's
  // list 1..n and saving only the rows whose number changed.
  const move = (index: number, delta: -1 | 1) => {
    const order = [...rows];
    const [row] = order.splice(index, 1);
    order.splice(index + delta, 0, row);
    const updates = order
      .map((r, i) => ({ id: r.id, sort_order: i + 1 }))
      .filter((u) => rows.find((r) => r.id === u.id)?.sort_order !== u.sort_order);
    run(row.id, () => reorderGatewaysAction(updates));
  };

  return (
    <div className="rounded-[var(--radius-card)] border border-line p-3">
      <h3 className="text-sm font-medium">
        {rows[0]?.country_name ?? country}{" "}
        <span className="text-muted">
          ({country}
          {currency ? ` · ${currency}` : ""})
        </span>
      </h3>
      <ul className="mt-2 space-y-2">
        {rows.map((row, index) => {
          const obstacle = gatewayObstacle(row);
          return (
            <li key={row.id} className="flex flex-wrap items-center gap-2">
              <span className="flex flex-col">
                <button
                  type="button"
                  onClick={() => move(index, -1)}
                  disabled={index === 0 || busy !== null}
                  aria-label={`Move ${row.gateway} up`}
                  className="text-xs leading-none text-muted hover:text-foreground disabled:opacity-30"
                >
                  ▲
                </button>
                <button
                  type="button"
                  onClick={() => move(index, 1)}
                  disabled={index === rows.length - 1 || busy !== null}
                  aria-label={`Move ${row.gateway} down`}
                  className="text-xs leading-none text-muted hover:text-foreground disabled:opacity-30"
                >
                  ▼
                </button>
              </span>
              <button
                type="button"
                onClick={() => run(row.id, () => setGatewayActiveAction(row.id, !row.is_active))}
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
              {obstacle && (
                <span
                  className={`rounded border px-2 py-0.5 text-xs ${
                    row.is_active
                      ? "border-warn/40 bg-warn/5 text-warn"
                      : "border-line text-muted"
                  }`}
                  role={row.is_active ? "alert" : undefined}
                  title="Why checkout would not show this method"
                >
                  {row.is_active ? "On but hidden — " : ""}
                  {obstacle}
                </span>
              )}
              <span className="ml-auto">
                {removing === row.id ? (
                  <span className="flex items-center gap-2 text-xs">
                    <span className="text-warn">Remove {row.gateway} from {country}?</span>
                    <button
                      type="button"
                      onClick={() => {
                        setRemoving(null);
                        run(row.id, () => removeGatewayAction(row.id));
                      }}
                      className="rounded bg-warn px-2 py-1 font-medium text-white hover:opacity-90"
                    >
                      Remove
                    </button>
                    <button
                      type="button"
                      onClick={() => setRemoving(null)}
                      className="rounded border border-line px-2 py-1 hover:border-accent"
                    >
                      Keep
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => setRemoving(row.id)}
                    disabled={busy !== null}
                    className="text-xs text-muted hover:text-warn disabled:opacity-30"
                  >
                    Remove
                  </button>
                )}
              </span>
            </li>
          );
        })}
      </ul>

      {addable.length > 0 && (
        <div className="mt-3 flex items-center gap-2 border-t border-line pt-3">
          <label className="sr-only" htmlFor={`add-gateway-${country}`}>
            Add a payment method to {country}
          </label>
          <select
            id={`add-gateway-${country}`}
            value={adding}
            onChange={(e) => setAdding(e.target.value)}
            className={`${FIELD} max-w-xs`}
          >
            <option value="">Add a method…</option>
            {addable.map((entry) => {
              const cantCharge =
                entry.supported_currencies.length > 0 &&
                currency &&
                !entry.supported_currencies.includes(currency);
              return (
                <option key={entry.code} value={entry.code}>
                  {entry.code}
                  {cantCharge ? ` — cannot charge ${currency}` : ""}
                </option>
              );
            })}
          </select>
          <button
            type="button"
            disabled={!adding || busy !== null}
            onClick={() => {
              const code = adding;
              setAdding("");
              run(null, () =>
                addGatewayAction({
                  country,
                  gateway: code,
                  sort_order: nextSortOrder(rows),
                }),
              );
            }}
            className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            Add
          </button>
          <span className="text-xs text-muted">Added methods start switched off.</span>
        </div>
      )}
    </div>
  );
}
