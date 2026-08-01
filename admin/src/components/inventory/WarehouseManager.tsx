"use client";

/**
 * The warehouse manager. Plan-17c Task 5.
 *
 * ── TWO THINGS ON THIS SCREEN ARE NOT ORDINARY EDITS ────────────────────────────────
 *
 * 1. `serves_countries` and `is_active` decide which warehouse `reserve()` may draw from.
 *    Untick NG on Lagos HQ and every checkout in the only sellable market fails, silently,
 *    until a customer tries to buy something. So both are gated behind a confirmation that
 *    NAMES the market about to lose its last warehouse, computed from the others rather
 *    than asserted (ruling 1b). Renaming a warehouse or changing its priority is not gated
 *    — those cannot strand anybody.
 *
 * 2. Two active warehouses at the same priority is a tie broken by primary key, i.e. by
 *    which was created first. Production ships both at priority 1. That is WARNED about
 *    rather than merely displayed: two identical numbers nobody chose do not tell anyone
 *    a decision is owed.
 *
 * FIELDS ARE CONTROLLED AND THE SUBMIT DISPATCHES THROUGH `startTransition`, for the
 * reason the categories panel learned the hard way: React resets a native `<form action>`
 * on completion, and the refreshed list lands a commit later, so an uncontrolled field
 * would show pre-save values immediately after a successful save — on a screen where the
 * pre-save value is a kill switch.
 */
import { startTransition, useState } from "react";
import { saveWarehouseAction } from "@/app/(shell)/inventory/warehouses/actions";
import {
  duplicatePriorities,
  strandedCountries,
  warehousesAtPriority,
  type WarehouseRow,
} from "@/lib/warehouses";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export interface CountryOption {
  code: string;
  name: string;
}

export function WarehouseManager({
  warehouses,
  countries,
}: {
  warehouses: WarehouseRow[];
  countries: CountryOption[];
}) {
  const [selectedId, setSelectedId] = useState<number | null>(warehouses[0]?.id ?? null);
  const selected = warehouses.find((w) => w.id === selectedId) ?? null;
  const ties = duplicatePriorities(warehouses);

  if (!warehouses.length) {
    return (
      <p className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center text-sm text-muted">
        No warehouses yet.
      </p>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <div>
        {ties.map((priority) => (
          <p
            key={priority}
            role="alert"
            className="mb-3 rounded border border-warn/30 bg-warn/5 p-3 text-sm text-warn"
          >
            <strong>
              {warehousesAtPriority(warehouses, priority)
                .map((w) => w.name)
                .join(" and ")}
            </strong>{" "}
            share priority {priority}. Allocation breaks that tie by whichever was created
            first, which is nobody&rsquo;s decision. Give them different priorities to choose
            deliberately.
          </p>
        ))}

        <div className="overflow-hidden rounded-[var(--radius-card)] border border-line">
          <ul>
            {warehouses.map((warehouse) => (
              <li key={warehouse.id} className="border-b border-line last:border-0">
                <button
                  type="button"
                  onClick={() => setSelectedId(warehouse.id)}
                  aria-current={warehouse.id === selectedId ? "true" : undefined}
                  className={`flex w-full flex-col gap-0.5 px-3 py-2 text-left text-sm hover:bg-surface ${
                    warehouse.id === selectedId ? "bg-accent/10" : ""
                  }`}
                >
                  <span className="flex items-center gap-2">
                    <span className={warehouse.is_active ? "" : "text-muted line-through"}>
                      {warehouse.name}
                    </span>
                    {!warehouse.is_active && (
                      <span className="rounded border border-line px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted">
                        Inactive
                      </span>
                    )}
                    <span className="ml-auto text-xs text-muted">priority {warehouse.priority}</span>
                  </span>
                  <span className="text-xs text-muted">
                    in {warehouse.location_country} · serves{" "}
                    {warehouse.serves_countries.length
                      ? warehouse.serves_countries.join(", ")
                      : "nowhere"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {selected && (
        // Keyed, so picking a different warehouse remounts the form with its values.
        <WarehouseForm
          key={selected.id}
          warehouse={selected}
          all={warehouses}
          countries={countries}
        />
      )}
    </div>
  );
}

function WarehouseForm({
  warehouse,
  all,
  countries,
}: {
  warehouse: WarehouseRow;
  all: WarehouseRow[];
  countries: CountryOption[];
}) {
  const [name, setName] = useState(warehouse.name);
  const [location, setLocation] = useState(warehouse.location_country);
  const [serves, setServes] = useState<string[]>(warehouse.serves_countries);
  const [priority, setPriority] = useState(String(warehouse.priority));
  const [isActive, setIsActive] = useState(warehouse.is_active);
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const stranded = strandedCountries(
    { id: warehouse.id, serves_countries: serves, is_active: isActive },
    all,
  );

  const nameOf = (code: string) => countries.find((c) => c.code === code)?.name ?? code;

  const save = () => {
    setPending(true);
    setSaved(false);
    setFieldErrors({});
    setMessage(null);
    startTransition(async () => {
      const state = await saveWarehouseAction({
        id: warehouse.id,
        name,
        location_country: location,
        serves_countries: serves,
        priority: Number(priority),
        is_active: isActive,
      });
      setPending(false);
      setConfirming(false);
      if (state.savedAt) setSaved(true);
      setFieldErrors(state.fieldErrors ?? {});
      setMessage(state.message ?? null);
    });
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // The gate: an edit that strands a market must be confirmed in words first.
    if (stranded.length && !confirming) {
      setConfirming(true);
      return;
    }
    save();
  };

  return (
    <form onSubmit={onSubmit} className="h-fit rounded-[var(--radius-card)] border border-line p-4">
      {message && (
        <p className="mb-3 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
          {message}
        </p>
      )}
      {saved && !message && (
        <p className="mb-3 rounded border border-ok/30 bg-ok/10 p-2 text-sm text-ok" role="status">
          Saved {warehouse.name}.
        </p>
      )}

      <div className="space-y-3">
        <label className="block text-xs text-muted">
          Name
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={`mt-1 ${FIELD}`}
          />
          {fieldErrors.name && <p className="mt-1 text-xs text-warn">{fieldErrors.name}</p>}
        </label>

        <label className="block text-xs text-muted">
          Physically in
          <select
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            className={`mt-1 ${FIELD}`}
          >
            {countries.map((country) => (
              <option key={country.code} value={country.code}>
                {country.name} ({country.code})
              </option>
            ))}
          </select>
        </label>

        <fieldset className="rounded border border-line p-2">
          <legend className="px-1 text-xs text-muted">Serves</legend>
          <p className="mb-2 px-1 text-xs text-muted">
            Orders from these countries can be filled from this warehouse.
          </p>
          {countries.map((country) => (
            <label key={country.code} className="flex items-center gap-2 px-1 py-0.5 text-sm">
              <input
                type="checkbox"
                checked={serves.includes(country.code)}
                onChange={(e) =>
                  setServes((current) =>
                    e.target.checked
                      ? [...current, country.code]
                      : current.filter((code) => code !== country.code),
                  )
                }
                className="h-4 w-4 rounded border-line"
              />
              {country.name} <span className="text-xs text-muted">({country.code})</span>
            </label>
          ))}
          {fieldErrors.serves_countries && (
            <p className="mt-1 px-1 text-xs text-warn">{fieldErrors.serves_countries}</p>
          )}
        </fieldset>

        <label className="block text-xs text-muted">
          Priority
          <input
            type="text"
            inputMode="numeric"
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            className={`mt-1 ${FIELD}`}
          />
          <span className="mt-1 block text-xs text-muted">Lower is tried first.</span>
          {fieldErrors.priority && <p className="mt-1 text-xs text-warn">{fieldErrors.priority}</p>}
        </label>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
            className="h-4 w-4 rounded border-line"
          />
          Active — stock here can be allocated
        </label>
      </div>

      {/* Ruling 1b. The consequence in plain words, naming the markets, before anything
          is sent. Deleting is not offered at all; this is the closest thing to it. */}
      {confirming && stranded.length > 0 && (
        <div className="mt-4 rounded border border-warn/40 bg-warn/5 p-3" role="alert">
          <p className="text-sm font-medium text-warn">
            {stranded.map(nameOf).join(", ")} will have no warehouse.
          </p>
          <p className="mt-1 text-sm text-warn">
            Checkout will fail there — an order cannot be reserved from anywhere else. Nothing
            warns a customer until they try to buy.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="submit"
              disabled={pending}
              className="rounded bg-warn px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
            >
              {pending ? "Saving…" : "Save anyway"}
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
          className="mt-4 w-full rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
        >
          {pending ? "Saving…" : "Save warehouse"}
        </button>
      )}
    </form>
  );
}
