"use client";
import { useEffect, useState } from "react";
import type { Region } from "@/components/checkout/RegionSelect";

interface AccountRegionSelectProps {
  country: string;
  stateValue?: number;
  areaValue?: number;
  onChange: (v: { state_region?: number; area_region?: number }) => void;
  labels?: { state: string; area: string };
}

/**
 * Account-owned twin of checkout/RegionSelect.tsx's State→LGA flow — `checkout/**`
 * stays frozen (Plan-15d Task 2 review, round 1), so this is a small duplicate rather
 * than a shared extraction.
 *
 * THE ONE BEHAVIOURAL DIFFERENCE, AND WHY IT EXISTS: RegionSelect only ever fetches a
 * state's LGAs from `handleStateChange` — a user CLICK. That's correct for create mode
 * (no state picked yet, so no LGAs to show), but wrong for edit mode: AddressForm can
 * mount with a saved `state_region`/`area_region` from the server, and nothing simulates
 * the click that would normally trigger the LGA fetch. The LGA select would render with
 * no matching `<option>` for the saved area — looks blank — and if the shopper re-picks
 * the same state to "fix" the blank LGA, the reset-on-state-change rule clears
 * `area_region`, so an unrelated edit (e.g. just the phone number) can silently drop the
 * stored LGA on save. This component fixes that by eagerly fetching the *initial*
 * state's LGAs once on mount (captured via `useState`'s lazy initializer, so a later
 * prop change to `stateValue` — same component instance re-rendering — does not
 * re-trigger it; only `handleStateChange`, the same as RegionSelect, owns fetching after
 * mount). All other behaviour (state fetch, state→LGA reset rule, disabled/loading
 * states) is copied verbatim from RegionSelect.
 */
export function AccountRegionSelect({
  country, stateValue, areaValue, onChange, labels,
}: AccountRegionSelectProps) {
  const [states, setStates] = useState<Region[] | null>(null);
  const [areas, setAreas] = useState<Region[] | null>(null);

  // Snapshot the state this component mounted with — the one edit-mode prefill needs
  // fetched. Deliberately NOT re-read from the `stateValue` prop after mount.
  const [prefillState] = useState(stateValue);
  // Seeded true when there's a prefill fetch coming, so the effect below never has to
  // call setState synchronously in its body (react-hooks/set-state-in-effect) — it only
  // clears the flag in a `finally`, after the awaited fetch.
  const [areasLoading, setAreasLoading] = useState(Boolean(prefillState));

  const stateLabel = labels?.state ?? "State";
  const areaLabel = labels?.area ?? "LGA";

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/regions?country=${encodeURIComponent(country)}`);
        const data = res.ok ? await res.json().catch(() => []) : [];
        if (!cancelled) setStates(Array.isArray(data) ? data : []);
      } catch {
        if (!cancelled) setStates([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [country]);

  // Edit-mode prefill: fetch the saved state's LGAs once, so a saved area_region has a
  // matching <option> from first paint instead of rendering blank.
  useEffect(() => {
    if (!prefillState) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/regions?parent=${prefillState}`);
        const data = res.ok ? await res.json().catch(() => []) : [];
        if (!cancelled) setAreas(Array.isArray(data) ? data : []);
      } catch {
        if (!cancelled) setAreas([]);
      } finally {
        if (!cancelled) setAreasLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [prefillState]);

  async function handleStateChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const id = e.target.value ? Number(e.target.value) : undefined;
    onChange({ state_region: id, area_region: undefined });
    setAreas(null);
    if (!id) return;
    setAreasLoading(true);
    try {
      const res = await fetch(`/api/regions?parent=${id}`);
      const data = res.ok ? await res.json().catch(() => []) : [];
      setAreas(Array.isArray(data) ? data : []);
    } catch {
      setAreas([]);
    } finally {
      setAreasLoading(false);
    }
  }

  function handleAreaChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const id = e.target.value ? Number(e.target.value) : undefined;
    onChange({ state_region: stateValue, area_region: id });
  }

  const statesLoading = states === null;

  if (!statesLoading && states.length === 0) {
    return (
      <p className="text-sm text-muted">
        No regions are set up for this country yet — leave the street address as detailed as
        possible.
      </p>
    );
  }

  // Same rule as RegionSelect: the second select only exists when the chosen state
  // actually has areas — GB/US/CA states have no seeded children.
  const chosenState = (states ?? []).find((s) => s.id === stateValue);
  const showAreaSelect = Boolean(chosenState?.has_children);

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div>
        <label htmlFor="account-region-state" className="mb-1 block text-sm font-medium">
          {stateLabel}
        </label>
        <select
          id="account-region-state"
          value={stateValue ?? ""}
          onChange={handleStateChange}
          disabled={statesLoading}
          required
          className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm"
        >
          <option value="">{statesLoading ? "Loading…" : `Select ${stateLabel.toLowerCase()}`}</option>
          {(states ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>
      {showAreaSelect && (
        <div>
          <label htmlFor="account-region-area" className="mb-1 block text-sm font-medium">
            {areaLabel}
          </label>
          <select
            id="account-region-area"
            value={areaValue ?? ""}
            onChange={handleAreaChange}
            disabled={areasLoading}
            required
            className="w-full rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm disabled:opacity-60"
          >
            <option value="">{areasLoading ? "Loading…" : `Select ${areaLabel.toLowerCase()}`}</option>
            {(areas ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
}
