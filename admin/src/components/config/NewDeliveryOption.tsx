"use client";

/**
 * The location-first create wizard.
 *
 * The FIRST decision is the place, not the price, because the country is load-bearing:
 * it pins the option's currency (checkout filters options to the order country's
 * currency — a mismatched option silently never appears), and it decides which region
 * tree to offer. The drill-down STOPS AT ANY LEVEL: pick Nigeria and stop for a
 * nationwide option, narrow to Lagos for a state option, or open Lagos and tick LGAs.
 * Forcing the full drill would make the two commonest real options — nationwide and
 * whole-state — the awkward path.
 *
 * One country per new option, on purpose: the currency rule means an option can only
 * ever serve same-currency countries anyway. The coverage page can broaden it later.
 *
 * Everything is created in ONE request (coverage rides on the POST), so there is no
 * window where a coverage-less option sits active and matches nobody.
 */
import { startTransition, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createDeliveryOptionAction } from "@/app/(shell)/settings/delivery/actions";
import { RegionTree } from "@/components/config/RegionTree";
import { buildTree, lowerLabel, pluralLabel, regionsOf, type RegionRow } from "@/lib/regions";
import type { CountryRef } from "@/lib/reference";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export function NewDeliveryOption({
  countries,
  regions,
}: {
  countries: CountryRef[];
  regions: RegionRow[];
}) {
  const router = useRouter();

  // ── Step 1: where ──────────────────────────────────────────────────────────
  const [countryCode, setCountryCode] = useState<string | null>(null);
  const [scope, setScope] = useState<"everywhere" | "specific">("everywhere");
  const [regionIds, setRegionIds] = useState<Set<number>>(new Set());
  const [step, setStep] = useState<1 | 2>(1);

  // ── Step 2: details ────────────────────────────────────────────────────────
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [freeOver, setFreeOver] = useState("");
  const [minDays, setMinDays] = useState("1");
  const [maxDays, setMaxDays] = useState("3");
  const [disclaimer, setDisclaimer] = useState("");
  const [quoteRequired, setQuoteRequired] = useState(false);
  const [pending, setPending] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);

  const country = countries.find((c) => c.code === countryCode) ?? null;
  const countryRegions = useMemo(
    () => (countryCode ? regionsOf(regions, countryCode) : []),
    [regions, countryCode],
  );
  const tree = useMemo(() => buildTree(countryRegions), [countryRegions]);
  const stateLabel = country?.state_label ?? "State";
  const areaLabel = country?.area_label ?? "Area";

  const pickCountry = (code: string) => {
    setCountryCode(code);
    // Regions belong to one country; a leftover Lagos id under a US option would be a
    // dead row the matcher never reaches.
    setRegionIds(new Set());
    setScope("everywhere");
  };

  const toggleRegion = (id: number) =>
    setRegionIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const whereSummary = !country
    ? ""
    : scope === "everywhere" || regionIds.size === 0
      ? `Everywhere in ${country.name}`
      : `${country.name} — ${summarizeSelection(tree, regionIds)}`;

  const whereDone =
    country !== null && (scope === "everywhere" || regionIds.size > 0);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!country) return;
    setPending(true);
    setErrors({});
    setMessage(null);
    startTransition(async () => {
      const state = await createDeliveryOptionAction({
        name,
        price,
        free_over: freeOver,
        min_days: minDays,
        max_days: maxDays,
        disclaimer,
        quote_required: quoteRequired,
        currency: country.currency?.code ?? "",
        country_codes: scope === "everywhere" ? [country.code] : [],
        region_ids: scope === "everywhere" ? [] : [...regionIds],
      });
      setPending(false);
      if (state.savedAt) {
        router.push("/settings/delivery");
        return;
      }
      setErrors(state.fieldErrors ?? {});
      setMessage(state.message ?? null);
    });
  };

  return (
    <div className="space-y-6">
      {/* ── Step 1: where ─────────────────────────────────────────────────── */}
      <section className="rounded-[var(--radius-card)] border border-line p-4">
        <h2 className="text-sm font-semibold">1 · Where is it offered?</h2>
        <p className="mt-1 text-sm text-muted">
          Start from the place — the country also sets the option&apos;s currency.
        </p>

        <ul className="mt-3 flex flex-wrap gap-2">
          {countries.map((c) => (
            <li key={c.code}>
              <button
                type="button"
                onClick={() => pickCountry(c.code)}
                className={`rounded-full border px-3 py-1 text-sm ${
                  countryCode === c.code
                    ? "border-accent bg-accent text-white"
                    : "border-line hover:border-accent"
                }`}
              >
                {c.name}
                {c.currency && (
                  <span className={countryCode === c.code ? "ml-1 opacity-80" : "ml-1 text-muted"}>
                    · {c.currency.code}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>

        {country && countryRegions.length > 0 && (
          <div className="mt-4 space-y-3">
            <div className="flex flex-wrap gap-2">
              <ScopeButton
                active={scope === "everywhere"}
                onClick={() => setScope("everywhere")}
                label={`Everywhere in ${country.name}`}
              />
              <ScopeButton
                active={scope === "specific"}
                onClick={() => setScope("specific")}
                label={`Only certain ${pluralLabel(stateLabel)} or ${pluralLabel(areaLabel)}`}
              />
            </div>
            {scope === "specific" && (
              <>
                <p className="text-sm text-muted">
                  Ticking a {lowerLabel(stateLabel)} covers every {lowerLabel(areaLabel)}{" "}
                  in it — including ones added later. Open one to pick{" "}
                  {pluralLabel(areaLabel)} individually.
                </p>
                <RegionTree
                  tree={tree}
                  selected={regionIds}
                  onToggle={toggleRegion}
                  areaLabel={pluralLabel(areaLabel)}
                />
              </>
            )}
          </div>
        )}
        {country && countryRegions.length === 0 && (
          <p className="mt-3 text-sm text-muted">
            {country.name} has no region list yet, so this option will cover the whole
            country.
          </p>
        )}

        {step === 1 && (
          <button
            type="button"
            disabled={!whereDone}
            onClick={() => setStep(2)}
            className="mt-4 rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            Continue
          </button>
        )}
      </section>

      {/* ── Step 2: details ───────────────────────────────────────────────── */}
      {step === 2 && country && (
        <form
          onSubmit={submit}
          className="rounded-[var(--radius-card)] border border-line p-4"
        >
          <h2 className="text-sm font-semibold">2 · What does it cost?</h2>
          <p className="mt-1 text-sm text-muted">{whereSummary}</p>

          {message && (
            <p className="mt-3 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
              {message}
            </p>
          )}

          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <label className="block text-xs text-muted">
              Name
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={`e.g. ${country.name} Standard`}
                className={`mt-1 ${FIELD}`}
              />
              {errors.name && <p className="mt-1 text-xs text-warn">{errors.name}</p>}
            </label>
            <label className="block text-xs text-muted">
              Price ({country.currency?.symbol ?? country.currency?.code ?? "?"})
              <input
                type="text"
                inputMode="decimal"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                className={`mt-1 ${FIELD}`}
              />
              {errors.price && <p className="mt-1 text-xs text-warn">{errors.price}</p>}
              {errors.currency && <p className="mt-1 text-xs text-warn">{errors.currency}</p>}
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
              {errors.disclaimer && (
                <p className="mt-1 text-xs text-warn">{errors.disclaimer}</p>
              )}
            </label>
          </div>

          <label className="mt-3 flex items-center gap-2 text-xs text-muted">
            <input
              type="checkbox"
              checked={quoteRequired}
              onChange={(e) => setQuoteRequired(e.target.checked)}
              className="h-4 w-4 rounded border-line"
            />
            The cost is quoted after the order (customers see the note, never a price)
          </label>

          {errors.country_codes && (
            <p className="mt-3 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn">
              {errors.country_codes}
            </p>
          )}

          <button
            type="submit"
            disabled={pending}
            className="mt-4 rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
          >
            {pending ? "Creating…" : "Create delivery option"}
          </button>
        </form>
      )}

      <p className="text-xs text-muted">
        <Link href="/settings/delivery" className="underline underline-offset-2 hover:text-accent">
          ← Back to delivery options
        </Link>
      </p>
    </div>
  );
}

function ScopeButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-sm ${
        active ? "border-accent bg-accent text-white" : "border-line hover:border-accent"
      }`}
    >
      {label}
    </button>
  );
}

/** "Lagos, Ogun + 3 areas" — a short human line for the step-2 header. */
function summarizeSelection(
  tree: ReturnType<typeof buildTree>,
  selected: Set<number>,
): string {
  const wholeStates: string[] = [];
  let areaCount = 0;
  for (const node of tree) {
    if (selected.has(node.state.id)) wholeStates.push(node.state.name);
    else areaCount += node.areas.filter((a) => selected.has(a.id)).length;
  }
  const parts: string[] = [];
  if (wholeStates.length) parts.push(wholeStates.join(", "));
  if (areaCount) parts.push(`${areaCount} ${areaCount === 1 ? "area" : "areas"}`);
  return parts.join(" + ") || "nowhere yet";
}
