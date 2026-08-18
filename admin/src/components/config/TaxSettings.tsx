"use client";

/**
 * The tax settings screen (Plan-37): one master switch, then a card per market.
 *
 * The layout answers the Owner's two real questions in order. "Is tax on at all?" is
 * the master card — flipping it saves IMMEDIATELY, because a switch that needs a
 * second click to mean anything will be left half-flipped. "What does each market
 * charge?" is a card per country with an explicit Save, because a rate is typed, and
 * saving keystrokes as they happen would write "2" on the way to "20".
 *
 * The summary line on each card ("VAT 7.5% · included in prices") is the scan layer —
 * the same idea as the delivery rows: read first, edit second.
 */
import { startTransition, useState } from "react";
import {
  saveTaxCountryAction,
  saveTaxMasterSwitchAction,
} from "@/app/(shell)/settings/taxes/actions";
import type { TaxCountryRow, TaxSettingsRow } from "@/lib/tax-config";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

function summary(row: TaxCountryRow, masterOn: boolean): string {
  if (!masterOn) return "not charged — tax is off store-wide";
  if (!row.charge_tax) return "not charged — switched off for this market";
  const rate = Number(row.tax_rate_percent);
  if (!rate) return "not charged — rate is 0%";
  const mode = row.prices_include_tax ? "included in prices" : "added at checkout";
  const delivery = row.tax_applies_to_delivery ? ", delivery taxed" : "";
  return `${row.tax_label} ${rate}% · ${mode}${delivery}`;
}

export function TaxSettings({
  settings,
  countries,
}: {
  settings: TaxSettingsRow;
  countries: TaxCountryRow[];
}) {
  const [masterOn, setMasterOn] = useState(settings.charge_tax);
  const [masterPending, setMasterPending] = useState(false);
  const [masterError, setMasterError] = useState<string | null>(null);

  const flipMaster = (next: boolean) => {
    const previous = masterOn;
    setMasterOn(next); // optimistic — snaps back if the save fails
    setMasterPending(true);
    setMasterError(null);
    startTransition(async () => {
      const state = await saveTaxMasterSwitchAction({ charge_tax: next });
      setMasterPending(false);
      if (!state.savedAt) {
        setMasterOn(previous);
        setMasterError(state.message ?? "The switch could not be saved.");
      }
    });
  };

  return (
    <div className="space-y-6">
      <section className="rounded-[var(--radius-card)] border border-line p-4">
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            checked={masterOn}
            disabled={masterPending}
            onChange={(e) => flipMaster(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-line"
          />
          <span>
            <span className="block text-sm font-medium">Charge tax on this store</span>
            <span className="mt-0.5 block text-xs text-muted">
              The master switch. When off, no market charges tax regardless of its own
              settings — customers pay exactly the listed price everywhere.
            </span>
          </span>
        </label>
        {masterError && (
          <p className="mt-2 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
            {masterError}
          </p>
        )}
        {!masterOn && !masterError && (
          <p className="mt-2 rounded border border-warn/30 bg-warn/5 p-2 text-xs text-warn" role="status">
            Tax is off store-wide. The per-market settings below are kept, but none of
            them apply until this is switched back on.
          </p>
        )}
      </section>

      <div className="space-y-4">
        {countries.map((row) => (
          <CountryCard key={row.code} row={row} masterOn={masterOn} />
        ))}
      </div>
    </div>
  );
}

function CountryCard({ row, masterOn }: { row: TaxCountryRow; masterOn: boolean }) {
  const [chargeTax, setChargeTax] = useState(row.charge_tax);
  const [rate, setRate] = useState(row.tax_rate_percent);
  const [includeTax, setIncludeTax] = useState(row.prices_include_tax);
  const [taxDelivery, setTaxDelivery] = useState(row.tax_applies_to_delivery);
  const [label, setLabel] = useState(row.tax_label);
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);

  const name = row.is_rest_of_world ? "International (rest of world)" : row.name;
  const charging = masterOn && row.charge_tax && Number(row.tax_rate_percent) > 0;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setPending(true);
    setSaved(false);
    setErrors({});
    setMessage(null);
    startTransition(async () => {
      const state = await saveTaxCountryAction({
        code: row.code,
        charge_tax: chargeTax,
        tax_rate_percent: rate,
        prices_include_tax: includeTax,
        tax_applies_to_delivery: taxDelivery,
        tax_label: label,
      });
      setPending(false);
      if (state.savedAt) setSaved(true);
      setErrors(state.fieldErrors ?? {});
      setMessage(state.message ?? null);
    });
  };

  return (
    <form onSubmit={submit} className="rounded-[var(--radius-card)] border border-line p-4">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold">
          {name} <span className="font-normal text-muted">· {row.currency_code}</span>
        </h2>
        <span className={`text-xs ${charging ? "text-ok" : "text-muted"}`}>
          {summary(row, masterOn)}
        </span>
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

      <label className="mt-3 flex items-center gap-2 text-xs text-muted">
        <input
          type="checkbox"
          checked={chargeTax}
          onChange={(e) => setChargeTax(e.target.checked)}
          className="h-4 w-4 rounded border-line"
        />
        Charge tax in this market
      </label>

      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block text-xs text-muted">
          Rate (%)
          <input
            type="text"
            inputMode="decimal"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            className={`mt-1 ${FIELD}`}
          />
          {errors.tax_rate_percent && (
            <p className="mt-1 text-xs text-warn">{errors.tax_rate_percent}</p>
          )}
        </label>
        <label className="block text-xs text-muted">
          Pricing
          <select
            value={includeTax ? "included" : "added"}
            onChange={(e) => setIncludeTax(e.target.value === "included")}
            className={`mt-1 ${FIELD}`}
          >
            <option value="included">Prices include tax</option>
            <option value="added">Tax added at checkout</option>
          </select>
        </label>
        <label className="block text-xs text-muted">
          Line label at checkout
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            maxLength={30}
            className={`mt-1 ${FIELD}`}
          />
          {errors.tax_label && <p className="mt-1 text-xs text-warn">{errors.tax_label}</p>}
        </label>
        <label className="mt-5 flex items-center gap-2 text-xs text-muted">
          <input
            type="checkbox"
            checked={taxDelivery}
            onChange={(e) => setTaxDelivery(e.target.checked)}
            className="h-4 w-4 rounded border-line"
          />
          Also tax the delivery fee
        </label>
      </div>

      {!includeTax && chargeTax && Number(rate) > 0 && (
        <p className="mt-3 text-xs text-muted">
          “Tax added at checkout” means customers pay the listed price <em>plus</em>{" "}
          {label.trim() || "tax"} — the total at checkout will be higher than the
          product page price.
        </p>
      )}

      <div className="mt-4">
        <button
          type="submit"
          disabled={pending}
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          {pending ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
  );
}
