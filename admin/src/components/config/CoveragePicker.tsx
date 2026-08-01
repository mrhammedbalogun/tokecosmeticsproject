"use client";

/**
 * Where a delivery option is offered — Plan-19d, the largest UI in Plan-19.
 *
 * ── 811 REGIONS, AND MIXED GRANULARITY ──────────────────────────────────────────────
 *
 * Nigeria has 37 states and 774 LGAs, and master-spec Decision 13 says an option may
 * cover whole countries, whole states, or individual areas IN ANY COMBINATION. So the
 * tree collapses by default and a state shows a tri-state: all, some, none. "Some" is
 * the state that matters — without it, a mixed selection would render identically to a
 * whole-state one and somebody would "tidy" it into the wrong thing.
 *
 * Ticking a state selects the STATE ROW, not its 20 areas. That is what the backend
 * matches on (`_covered_region_ids` walks an address's ancestors), and it means a new LGA
 * added to Lagos next year is covered automatically rather than silently missing.
 *
 * ── THE TEST WIDGET IS A MIRROR, NOT THE RULE ───────────────────────────────────────
 *
 * "Would this address get this option?" is answered here by `coversAddress`, which
 * reproduces the backend's ancestor walk. The backend still decides at checkout. It earns
 * its place because coverage is otherwise invisible until a customer cannot check out.
 */
import { startTransition, useMemo, useState } from "react";
import { saveCoverageAction } from "@/app/(shell)/settings/delivery/actions";
import {
  buildTree,
  coversAddress,
  stateSelection,
  type RegionRow,
} from "@/lib/regions";

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
  countries: { code: string; name: string }[];
  regions: RegionRow[];
  selectedCountryCodes: string[];
  selectedRegionIds: number[];
}) {
  const tree = useMemo(() => buildTree(regions), [regions]);
  const [countryCodes, setCountryCodes] = useState<Set<string>>(
    new Set(selectedCountryCodes),
  );
  const [regionIds, setRegionIds] = useState<Set<number>>(new Set(selectedRegionIds));
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  // The test widget's inputs.
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

  const testStateId = testState ? Number(testState) : null;
  const testAreaId = testArea ? Number(testArea) : null;
  const testAreas = tree.find((n) => n.state.id === testStateId)?.areas ?? [];
  const testResult =
    testStateId === null
      ? null
      : coversAddress(
          { countryCode: "NG", stateId: testStateId, areaId: testAreaId },
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
          Ticking a country serves every address in it, whatever the states below say.
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

      <section className="rounded-[var(--radius-card)] border border-line p-4">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-semibold">States and areas</h2>
          <span className="text-xs text-muted">
            {regionIds.size} selected of {regions.length}
          </span>
        </div>
        <p className="mt-1 text-sm text-muted">
          Ticking a state covers every area in it — including ones added later.
        </p>

        <ul className="mt-3 max-h-[28rem] divide-y divide-line overflow-y-auto rounded border border-line">
          {tree.map((node) => {
            const selection = stateSelection(node, regionIds);
            const isOpen = expanded.has(node.state.id);
            return (
              <li key={node.state.id}>
                <div className="flex items-center gap-2 px-3 py-2">
                  <input
                    type="checkbox"
                    checked={selection === "all"}
                    ref={(el) => {
                      // The tri-state. Without it a partial pick looks like no pick.
                      if (el) el.indeterminate = selection === "some";
                    }}
                    onChange={() => toggleRegion(node.state.id)}
                    className="h-4 w-4 rounded border-line"
                    aria-label={`Serve all of ${node.state.name}`}
                  />
                  <button
                    type="button"
                    onClick={() =>
                      setExpanded((current) => {
                        const next = new Set(current);
                        if (next.has(node.state.id)) next.delete(node.state.id);
                        else next.add(node.state.id);
                        return next;
                      })
                    }
                    className="flex flex-1 items-center justify-between text-left text-sm hover:text-accent"
                  >
                    <span>
                      {node.state.name}
                      {selection === "some" && (
                        <span className="ml-2 text-xs text-accent">part</span>
                      )}
                      {!node.state.is_active && (
                        <span className="ml-2 text-xs text-muted">(hidden)</span>
                      )}
                    </span>
                    <span className="text-xs text-muted">
                      {node.areas.length} areas {isOpen ? "▲" : "▼"}
                    </span>
                  </button>
                </div>
                {isOpen && node.areas.length > 0 && (
                  <ul className="bg-surface/50 pb-2 pl-9 pr-3">
                    {node.areas.map((area) => (
                      <li key={area.id}>
                        <label className="flex items-center gap-2 py-0.5 text-sm">
                          <input
                            type="checkbox"
                            checked={regionIds.has(area.id) || regionIds.has(node.state.id)}
                            disabled={regionIds.has(node.state.id)}
                            onChange={() => toggleRegion(area.id)}
                            className="h-4 w-4 rounded border-line"
                          />
                          <span className={regionIds.has(node.state.id) ? "text-muted" : ""}>
                            {area.name}
                          </span>
                        </label>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>

        <button
          type="button"
          onClick={save}
          disabled={pending}
          className="mt-3 rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
        >
          {pending ? "Saving…" : "Save coverage"}
        </button>
      </section>

      <section className="rounded-[var(--radius-card)] border border-line p-4">
        <h2 className="text-sm font-semibold">Test an address</h2>
        <p className="mt-1 text-sm text-muted">
          Would a customer here be offered this option? Unsaved ticks count, so you can
          check before committing.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="block text-xs text-muted">
            State
            <select
              value={testState}
              onChange={(e) => {
                setTestState(e.target.value);
                setTestArea("");
              }}
              className={`mt-1 ${FIELD}`}
            >
              <option value="">Choose a state…</option>
              {tree.map((node) => (
                <option key={node.state.id} value={node.state.id}>
                  {node.state.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs text-muted">
            Area
            <select
              value={testArea}
              onChange={(e) => setTestArea(e.target.value)}
              disabled={!testAreas.length}
              className={`mt-1 ${FIELD}`}
            >
              <option value="">Anywhere in the state</option>
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
