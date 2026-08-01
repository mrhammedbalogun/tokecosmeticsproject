"use client";

/**
 * Delivery options (Plan-19b) — the flat fields only.
 *
 * This is plausibly the most frequent config edit a Lagos store makes: fuel and logistics
 * costs move, and until now changing the Lagos delivery price meant a database client.
 * Coverage (which countries and which of 811 regions an option serves) is shown but not
 * editable here — that is 19d's tree, and a half-answer would be worse than none.
 */
import { startTransition, useState } from "react";
import { saveDeliveryOptionAction } from "@/app/(shell)/settings/delivery/actions";
import type { DeliveryOptionRow } from "@/lib/money-config";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export function DeliveryOptions({ options }: { options: DeliveryOptionRow[] }) {
  if (!options.length) {
    return (
      <p className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center text-sm text-muted">
        No delivery options yet.
      </p>
    );
  }
  return (
    <div className="space-y-4">
      {options.map((option) => (
        <OptionCard key={option.id} option={option} />
      ))}
    </div>
  );
}

function OptionCard({ option }: { option: DeliveryOptionRow }) {
  const [name, setName] = useState(option.name);
  const [price, setPrice] = useState(option.price);
  const [freeOver, setFreeOver] = useState(option.free_over ?? "");
  const [minDays, setMinDays] = useState(String(option.min_days));
  const [maxDays, setMaxDays] = useState(String(option.max_days));
  const [disclaimer, setDisclaimer] = useState(option.disclaimer);
  const [isActive, setIsActive] = useState(option.is_active);
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setPending(true);
    setSaved(false);
    setErrors({});
    setMessage(null);
    startTransition(async () => {
      const state = await saveDeliveryOptionAction({
        id: option.id, name, price, free_over: freeOver,
        min_days: minDays, max_days: maxDays, disclaimer, is_active: isActive,
      });
      setPending(false);
      if (state.savedAt) setSaved(true);
      setErrors(state.fieldErrors ?? {});
      setMessage(state.message ?? null);
    });
  };

  return (
    <form onSubmit={submit} className="rounded-[var(--radius-card)] border border-line p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-medium">
          {option.name}{" "}
          <span className="text-xs text-muted">
            · {option.country_codes.join(", ") || "no countries"}
            {option.region_count > 0 && ` · ${option.region_count} regions`}
          </span>
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
          Name
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} className={`mt-1 ${FIELD}`} />
          {errors.name && <p className="mt-1 text-xs text-warn">{errors.name}</p>}
        </label>
        <label className="block text-xs text-muted">
          Price ({option.currency})
          <input
            type="text"
            inputMode="decimal"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            className={`mt-1 ${FIELD}`}
          />
          {errors.price && <p className="mt-1 text-xs text-warn">{errors.price}</p>}
        </label>
        <label className="block text-xs text-muted">
          Free over
          <input
            type="text"
            inputMode="decimal"
            value={freeOver}
            onChange={(e) => setFreeOver(e.target.value)}
            placeholder="never"
            className={`mt-1 ${FIELD}`}
          />
        </label>
        <label className="block text-xs text-muted">
          Fastest (days)
          <input
            type="text"
            inputMode="numeric"
            value={minDays}
            onChange={(e) => setMinDays(e.target.value)}
            className={`mt-1 ${FIELD}`}
          />
          {errors.min_days && <p className="mt-1 text-xs text-warn">{errors.min_days}</p>}
        </label>
        <label className="block text-xs text-muted">
          Slowest (days)
          <input
            type="text"
            inputMode="numeric"
            value={maxDays}
            onChange={(e) => setMaxDays(e.target.value)}
            className={`mt-1 ${FIELD}`}
          />
        </label>
        <label className="block text-xs text-muted">
          Note shown instead of a price
          <input
            type="text"
            value={disclaimer}
            onChange={(e) => setDisclaimer(e.target.value)}
            className={`mt-1 ${FIELD}`}
          />
        </label>
      </div>

      <button
        type="submit"
        disabled={pending}
        className="mt-3 rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
      >
        {pending ? "Saving…" : "Save option"}
      </button>
      <p className="mt-2 text-xs text-muted">
        Which places this option covers is set in a later slice; it is shown above so you
        can tell the options apart.
      </p>
    </form>
  );
}
