"use client";

/**
 * Where a delivery option is offered — Plan-19d, generalised for the
 * Countries_breakdown work (no longer hardcoded to Nigeria).
 *
 * ── MIXED GRANULARITY ───────────────────────────────────────────────────────────────
 *
 * Master-spec Decision 13: an option may cover whole countries, whole states, or
 * individual areas IN ANY COMBINATION. Each country that has a Region tree gets its own
 * section, labelled with ITS levels ("States and LGAs" for NG, "Provinces and
 * municipalities" for CA). Ticking a state selects the STATE ROW, not its areas — that
 * is what the backend matches on (`_covered_region_ids` walks an address's ancestors),
 * and it means an LGA added to Lagos next year is covered automatically rather than
 * silently missing. The tri-state rendering lives in RegionTree, shared with the
 * create wizard.
 *
 * ── THE TEST WIDGET IS A MIRROR, NOT THE RULE ───────────────────────────────────────
 *
 * "Would this address get this option?" is answered here by `coversAddress`, which
 * reproduces the backend's ancestor walk on UNSAVED ticks — check before committing.
 * The backend still decides at checkout; the global tester on the delivery list asks
 * it for real.
 */
import { startTransition, useMemo, useState } from "react";
import { saveCoverageAction } from "@/app/(shell)/settings/delivery/actions";
import { RegionTree } from "@/components/config/RegionTree";
import {
  buildTree,
  coversAddress,
  lowerLabel,
  pluralLabel,
  regionsOf,
  type RegionRow,
} from "@/lib/regions";
import type { CountryRef } from "@/lib/reference";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export function CoveragePicker({
  optionId,
  optionName,
  countries,
  regions,
  selectedCountryCodes,
  selectedRegionIds,
}: {
  optionId: number;
  optionName: string;
  countries: CountryRef[];
  regions: RegionRow[];
  selectedCountryCodes: string[];
  selectedRegionIds: number[];
}) {
  const [countryCodes, setCountryCodes] = useState<Set<string>>(
    new Set(selectedCountryCodes),
  );
  const [regionIds, setRegionIds] = useState<Set<number>>(new Set(selectedRegionIds));
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  // Countries that have a region tree each get a section.
  const regionCountries = useMemo(
    () =>
      countries
        .map((country) => ({
          country,
          tree: buildTree(regionsOf(regions, country.code)),
        }))
        .filter((entry) => entry.tree.length > 0),
    [countries, regions],
  );

  // The test widget's inputs.
  const [testCountry, setTestCountry] = useState<string>(
    regionCountries[0]?.country.code ?? "",
  );
  const [testState, setTestState] = useState<string>("");
  const [testArea, setTestArea] = useState<string>("");

  const toggleCountry = (code: string) =>
    setCountryCodes((current) => {
      const next = new Set(current);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });

  const toggleRegion = (id: number) =>
    setRegionIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const save = () => {
    setPending(true);
    setSaved(false);
    setMessage(null);
    startTransition(async () => {
      const state = await saveCoverageAction({
        id: optionId,
        country_codes: [...countryCodes],
        region_ids: [...regionIds],
      });
      setPending(false);
      if (state.savedAt) setSaved(true);
      setMessage(state.message ?? null);
    });
  };

  const testEntry = regionCountries.find((e) => e.country.code === testCountry);
  const testTree = testEntry?.tree ?? [];
  const testStateId = testState ? Number(testState) : null;
  const testAreaId = testArea ? Number(testArea) : null;
  const testAreas = testTree.find((n) => n.state.id === testStateId)?.areas ?? [];
  const testResult =
    testStateId === null
      ? null
      : coversAddress(
          { countryCode: testCountry, stateId: testStateId, areaId: testAreaId },
          { countryCodes: [...countryCodes], regionIds },
        );

  return (
    <div className="space-y-6">
      {message && (
        <p className="rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
          {message}
        </p>
      )}
      {saved && !message && (
        <p className="rounded border border-ok/30 bg-ok/10 p-2 text-sm text-ok" role="status">
          Coverage saved for {optionName}.
        </p>
      )}

      <section className="rounded-[var(--radius-card)] border border-line p-4">
        <h2 className="text-sm font-semibold">Whole countries</h2>
        <p className="mt-1 text-sm text-muted">
          Ticking a country serves every address in it, whatever the regions below say.
        </p>
        <ul className="mt-3 flex flex-wrap gap-2">
          {countries.map((country) => (
            <li key={country.code}>
              <label className="flex items-center gap-2 rounded-full border border-line px-3 py-1 text-sm">
                <input
                  type="checkbox"
                  checked={countryCodes.has(country.code)}
                  onChange={() => toggleCountry(country.code)}
                  className="h-4 w-4 rounded border-line"
                />
                {country.name}
              </label>
            </li>
          ))}
        </ul>
      </section>

      {regionCountries.map(({ country, tree }) => {
        const stateLabel = country.state_label ?? "State";
        const areaLabel = country.area_label ?? "Area";
        const selectedHere = tree.reduce(
          (n, node) =>
            n +
            (regionIds.has(node.state.id) ? 1 : 0) +
            node.areas.filter((a) => regionIds.has(a.id)).length,
          0,
        );
        return (
          <section
            key={country.code}
            className="rounded-[var(--radius-card)] border border-line p-4"
          >
            <div className="flex items-baseline justify-between gap-3">
              <h2 className="text-sm font-semibold">
                {country.name}: {capitalPlural(stateLabel)} and {pluralLabel(areaLabel)}
              </h2>
              <span className="text-xs text-muted">{selectedHere} selected</span>
            </div>
            <p className="mt-1 text-sm text-muted">
              Ticking a {lowerLabel(stateLabel)} covers every {lowerLabel(areaLabel)}{" "}
              in it — including ones added later.
              {countryCodes.has(country.code) &&
                ` All of ${country.name} is already ticked above, so these add nothing until that is unticked.`}
            </p>
            <div className="mt-3">
              <RegionTree
                tree={tree}
                selected={regionIds}
                onToggle={toggleRegion}
                areaLabel={pluralLabel(areaLabel)}
              />
            </div>
          </section>
        );
      })}

      <button
        type="button"
        onClick={save}
        disabled={pending}
        className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
      >
        {pending ? "Saving…" : "Save coverage"}
      </button>

      <section className="rounded-[var(--radius-card)] border border-line p-4">
        <h2 className="text-sm font-semibold">Test an address</h2>
        <p className="mt-1 text-sm text-muted">
          Would a customer here be offered this option? Unsaved ticks count, so you can
          check before committing.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <label className="block text-xs text-muted">
            Country
            <select
              value={testCountry}
              onChange={(e) => {
                setTestCountry(e.target.value);
                setTestState("");
                setTestArea("");
              }}
              className={`mt-1 ${FIELD}`}
            >
              {regionCountries.map(({ country }) => (
                <option key={country.code} value={country.code}>
                  {country.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs text-muted">
            {testEntry?.country.state_label ?? "State"}
            <select
              value={testState}
              onChange={(e) => {
                setTestState(e.target.value);
                setTestArea("");
              }}
              className={`mt-1 ${FIELD}`}
            >
              <option value="">Choose…</option>
              {testTree.map((node) => (
                <option key={node.state.id} value={node.state.id}>
                  {node.state.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs text-muted">
            {testEntry?.country.area_label ?? "Area"}
            <select
              value={testArea}
              onChange={(e) => setTestArea(e.target.value)}
              disabled={!testAreas.length}
              className={`mt-1 ${FIELD}`}
            >
              <option value="">
                Anywhere in the {lowerLabel(testEntry?.country.state_label ?? "state")}
              </option>
              {testAreas.map((area) => (
                <option key={area.id} value={area.id}>
                  {area.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {testResult !== null && (
          <p
            className={`mt-3 rounded border p-2 text-sm ${
              testResult ? "border-ok/40 bg-ok/5 text-ok" : "border-warn/40 bg-warn/5 text-warn"
            }`}
            role="status"
          >
            {testResult
              ? "Offered — this address would see this option at checkout."
              : "Not offered — this address would not see this option."}
          </p>
        )}
      </section>
    </div>
  );
}

/** Capitalised plural for headings: "State" -> "States", "Country" -> "Countries". */
function capitalPlural(label: string): string {
  return label.endsWith("y") ? `${label.slice(0, -1)}ies` : `${label}s`;
}
