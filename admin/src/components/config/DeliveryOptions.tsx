"use client";

/**
 * The delivery options list, reorganised (2026-08-05).
 *
 * ── SCAN FIRST, EDIT SECOND ─────────────────────────────────────────────────────────
 *
 * The old page rendered every option as a permanently-open edit form — a wall of
 * identical inputs where finding "the Lagos price" meant reading field labels. Now the
 * page is COLLAPSED ROWS under STATIC country headers: name, a human coverage sentence,
 * the price and ETA — everything needed to scan — with the form one click away, expanded
 * IN PLACE so the list context never disappears. The headers are deliberately not
 * collapsible: most markets have one option, and a section that hides its single row
 * behind a click is chrome, not organisation.
 *
 * Rows stay MOUNTED once expanded (hidden, not unmounted, on collapse) so an accidental
 * collapse cannot destroy unsaved edits.
 *
 * ── SENTENCES THAT DO NOT LIE ───────────────────────────────────────────────────────
 *
 * A carrier option's coverage M2M says "NG", but its real footprint is whatever the
 * carrier serves (GIG: ~100 home-delivery LGAs) plus a live quote — so it reads
 * "Nigeria · where GIG delivers, quoted live", never "Everywhere in Nigeria". The
 * rest-of-world row is "Anywhere else in the world", pinned last, not alphabetised
 * among countries.
 *
 * ── DELETE ──────────────────────────────────────────────────────────────────────────
 *
 * Two-step inline confirm (no window.confirm — it blocks the extension automation, see
 * InvitePanel). The confirm strip names what is being deleted and warns when the option
 * is the LAST ACTIVE cover for a market — the actual disaster, a stranded checkout.
 * The same warning appears when unticking "Offered at checkout" would strand a market:
 * a guard only on the rarer path would be theatre.
 */
import { startTransition, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  deleteDeliveryOptionAction,
  saveDeliveryOptionAction,
} from "@/app/(shell)/settings/delivery/actions";
import type { DeliveryOptionRow } from "@/lib/money-config";
import type { CountryRef } from "@/lib/reference";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

// ── market + sentence helpers ─────────────────────────────────────────────────

/** The country codes an option serves: whole countries ∪ its regions' countries. */
function marketsOf(option: DeliveryOptionRow): string[] {
  const codes = new Set(option.coverage.countries.map((c) => c.code));
  for (const region of option.coverage.regions) codes.add(region.country_code);
  // The coverage regions are capped server-side, but one option's regions are
  // single-country in practice (the currency guard sees to it), so the cap cannot
  // hide a country here.
  return [...codes];
}

function coverageSentence(
  option: DeliveryOptionRow,
  countryByCode: Map<string, CountryRef>,
): string {
  const countryName = (code: string) => {
    const country = countryByCode.get(code);
    if (country?.is_rest_of_world) return "Rest of world";
    return country?.name ?? code;
  };

  if (option.kind === "carrier") {
    const names = marketsOf(option).map(countryName).join(" and ") || "—";
    return `${names} · where ${option.carrier_code.toUpperCase() || "the carrier"} delivers, quoted live`;
  }

  const parts: string[] = [];
  const wholeCountries = option.coverage.countries;
  if (wholeCountries.length) {
    const restOfWorld = wholeCountries.filter((c) => countryByCode.get(c.code)?.is_rest_of_world);
    const named = wholeCountries.filter((c) => !countryByCode.get(c.code)?.is_rest_of_world);
    if (named.length) parts.push(`Everywhere in ${named.map((c) => c.name).join(" and ")}`);
    if (restOfWorld.length) parts.push("Anywhere else in the world");
  }

  if (option.coverage.regions.length) {
    const names = option.coverage.regions.map((r) =>
      r.parent_name ? `${r.name} (${r.parent_name})` : r.name,
    );
    const hidden = option.coverage.region_total - option.coverage.regions.length;
    parts.push(names.join(", ") + (hidden > 0 ? ` + ${hidden} more` : ""));
  }

  return parts.join(" · ") || "Covers nowhere — never offered";
}

function formatPrice(price: string, symbol: string): string {
  const n = Number(price);
  if (!Number.isFinite(n)) return `${symbol}${price}`;
  const opts =
    n % 1 === 0
      ? { maximumFractionDigits: 0 }
      : { minimumFractionDigits: 2, maximumFractionDigits: 2 };
  return symbol + n.toLocaleString("en", opts);
}

function eta(option: DeliveryOptionRow): string {
  if (option.min_days === option.max_days) {
    return option.min_days === 0
      ? "same day"
      : `${option.min_days} day${option.min_days === 1 ? "" : "s"}`;
  }
  return `${option.min_days}–${option.max_days} days`;
}

/** Market codes for which this option is the ONLY active cover — deleting or
 * deactivating it leaves customers there with nothing at checkout. */
function soleActiveMarkets(option: DeliveryOptionRow, all: DeliveryOptionRow[]): string[] {
  if (!option.is_active) return [];
  const others = all.filter((o) => o.id !== option.id && o.is_active);
  return marketsOf(option).filter(
    (code) => !others.some((o) => marketsOf(o).includes(code)),
  );
}

// ── the list ──────────────────────────────────────────────────────────────────

export function DeliveryOptions({
  options,
  countries,
}: {
  options: DeliveryOptionRow[];
  countries: CountryRef[];
}) {
  const router = useRouter();
  const [removedIds, setRemovedIds] = useState<Set<number>>(new Set());
  const rows = options.filter((o) => !removedIds.has(o.id));

  const countryByCode = useMemo(
    () => new Map(countries.map((c) => [c.code, c])),
    [countries],
  );
  const symbolByCurrency = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of countries) if (c.currency) map.set(c.currency.code, c.currency.symbol);
    return map;
  }, [countries]);

  // Group by the option's market set — one row per option, never duplicated across
  // groups (a US + Rest-of-world option gets a combined header; two component
  // instances for one option would hold silently-diverging edit state). NG (the
  // default market) leads, Rest of world trails, others alphabetise between them.
  const groups = useMemo(() => {
    const byKey = new Map<string, { label: string; sortKey: string; rows: DeliveryOptionRow[] }>();
    for (const option of rows) {
      const codes = marketsOf(option).sort();
      const key = codes.join("+") || "?";
      if (!byKey.has(key)) {
        const names = codes.map((code) => {
          const country = countryByCode.get(code);
          return country?.is_rest_of_world ? "Rest of world" : (country?.name ?? code);
        });
        const isDefault = codes.some((code) => countryByCode.get(code)?.is_default);
        const isRest = codes.every((code) => countryByCode.get(code)?.is_rest_of_world);
        byKey.set(key, {
          label: names.join(" + ") || "Unassigned",
          sortKey: `${isDefault ? "0" : isRest ? "2" : "1"}:${names.join("+")}`,
          rows: [],
        });
      }
      byKey.get(key)!.rows.push(option);
    }
    return [...byKey.values()].sort((a, b) => a.sortKey.localeCompare(b.sortKey));
  }, [rows, countryByCode]);

  if (!rows.length) {
    return (
      <p className="rounded-[var(--radius-card)] border border-dashed border-line p-6 text-center text-sm text-muted">
        No delivery options yet — add one to start offering delivery at checkout.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <section key={group.label}>
          <div className="flex items-baseline justify-between gap-3 border-b border-line pb-2">
            <h2 className="text-sm font-semibold">{group.label}</h2>
            <span className="text-xs text-muted">
              {group.rows.length} option{group.rows.length === 1 ? "" : "s"} ·{" "}
              {group.rows.filter((o) => o.is_active).length} offered at checkout
            </span>
          </div>
          <ul className="divide-y divide-line">
            {group.rows.map((option) => (
              <OptionRow
                key={option.id}
                option={option}
                allOptions={rows}
                countryByCode={countryByCode}
                symbol={symbolByCurrency.get(option.currency) ?? `${option.currency} `}
                onDeleted={(id) => {
                  setRemovedIds((current) => new Set(current).add(id));
                  router.refresh();
                }}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

// ── one row ───────────────────────────────────────────────────────────────────

function OptionRow({
  option,
  allOptions,
  countryByCode,
  symbol,
  onDeleted,
}: {
  option: DeliveryOptionRow;
  allOptions: DeliveryOptionRow[];
  countryByCode: Map<string, CountryRef>;
  symbol: string;
  onDeleted: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [everOpened, setEverOpened] = useState(false);

  const sentence = coverageSentence(option, countryByCode);
  const stranded = soleActiveMarkets(option, allOptions).map(
    (code) =>
      (countryByCode.get(code)?.is_rest_of_world
        ? "Rest of world"
        : countryByCode.get(code)?.name) ?? code,
  );

  const priceDisplay =
    option.kind === "carrier" ? (
      <span className="text-muted">quoted live</span>
    ) : option.quote_required ? (
      <span className="text-muted">quoted after order</span>
    ) : (
      <span className="font-medium">{formatPrice(option.price, symbol)}</span>
    );

  return (
    <li>
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
          setEverOpened(true);
        }}
        aria-expanded={open}
        className="flex w-full items-center gap-3 py-3 text-left hover:bg-surface/60"
      >
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${option.is_active ? "bg-ok" : "border border-line bg-transparent"}`}
          title={option.is_active ? "Offered at checkout" : "Not offered"}
        />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">
            {option.name}
            {!option.is_active && (
              <span className="ml-2 rounded-full border border-line px-2 py-0.5 text-xs font-normal text-muted">
                not offered
              </span>
            )}
          </span>
          <span className="mt-0.5 block truncate text-xs text-muted">{sentence}</span>
        </span>
        <span className="shrink-0 text-right text-sm">
          {priceDisplay}
          <span className="ml-2 text-xs text-muted">{eta(option)}</span>
        </span>
        <span className="shrink-0 text-xs text-muted" aria-hidden>
          {open ? "▲" : "▼"}
        </span>
      </button>

      {everOpened && (
        <div className={open ? "pb-4 pl-5" : "hidden"}>
          <OptionEditor option={option} strandedIfOff={stranded} onDeleted={onDeleted} />
        </div>
      )}
    </li>
  );
}

// ── the editor (the old card, now living inside an expanded row) ──────────────

function OptionEditor({
  option,
  strandedIfOff,
  onDeleted,
}: {
  option: DeliveryOptionRow;
  strandedIfOff: string[];
  onDeleted: (id: number) => void;
}) {
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

  // Delete is a two-step: "Delete…" arms the red strip, the strip commits.
  const [armed, setArmed] = useState(false);
  const [deleting, setDeleting] = useState(false);

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

  const remove = () => {
    setDeleting(true);
    startTransition(async () => {
      const state = await deleteDeliveryOptionAction({ id: option.id });
      setDeleting(false);
      if (state.savedAt) {
        onDeleted(option.id);
        return;
      }
      setArmed(false);
      setMessage(state.message ?? "That option could not be deleted.");
    });
  };

  return (
    <form onSubmit={submit} className="rounded-[var(--radius-card)] border border-line p-4">
      {message && (
        <p className="mb-3 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
          {message}
        </p>
      )}
      {saved && !message && (
        <p className="mb-3 rounded border border-ok/30 bg-ok/10 p-2 text-sm text-ok" role="status">
          Saved.
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
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

      <label className="mt-3 flex items-center gap-2 text-xs text-muted">
        <input
          type="checkbox"
          checked={isActive}
          onChange={(e) => setIsActive(e.target.checked)}
          className="h-4 w-4 rounded border-line"
        />
        Offered at checkout
      </label>
      {!isActive && option.is_active && strandedIfOff.length > 0 && (
        <p className="mt-2 rounded border border-warn/40 bg-warn/5 p-2 text-xs text-warn" role="alert">
          This is the only option offered in {strandedIfOff.join(" and ")} — saving this
          leaves customers there with no delivery at checkout.
        </p>
      )}

      <div className="mt-3 flex items-center gap-4">
        <button
          type="submit"
          disabled={pending}
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
        >
          {pending ? "Saving…" : "Save option"}
        </button>
        <Link
          href={`/settings/delivery/${option.id}`}
          className="text-xs text-muted underline underline-offset-2 hover:text-accent"
        >
          Where it is offered →
        </Link>
        {!armed && (
          <button
            type="button"
            onClick={() => setArmed(true)}
            className="ml-auto text-xs text-warn underline underline-offset-2 hover:opacity-80"
          >
            Delete this option…
          </button>
        )}
      </div>

      {armed && (
        <div
          className="mt-3 rounded border border-warn/50 bg-warn/5 p-3"
          role="alertdialog"
          aria-label={`Delete ${option.name}`}
        >
          <p className="text-sm font-medium text-warn">Delete “{option.name}”?</p>
          <p className="mt-1 text-xs text-muted">
            Past orders keep only its name; everything else — price, coverage, settings —
            is gone for good. To pause it instead, untick “Offered at checkout”.
          </p>
          {strandedIfOff.length > 0 && (
            <p className="mt-2 text-xs font-medium text-warn">
              This is the only option offered in {strandedIfOff.join(" and ")} — deleting
              it leaves customers there with no delivery at checkout.
            </p>
          )}
          <div className="mt-3 flex items-center gap-3">
            <button
              type="button"
              onClick={remove}
              disabled={deleting}
              className="rounded bg-warn px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
            >
              {deleting ? "Deleting…" : "Delete for good"}
            </button>
            <button
              type="button"
              onClick={() => setArmed(false)}
              className="text-sm text-muted underline hover:text-foreground"
            >
              Keep it
            </button>
          </div>
        </div>
      )}
    </form>
  );
}
