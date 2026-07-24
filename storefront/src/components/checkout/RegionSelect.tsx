"use client";
import { useEffect, useState } from "react";

export interface Region {
  id: number;
  name: string;
  level: string;
  has_children: boolean;
}

interface RegionSelectProps {
  country: string;
  stateValue?: number;
  areaValue?: number;
  onChange: (v: { state_region?: number; area_region?: number }) => void;
  labels?: { state: string; area: string };
}

/** Two dependent `<select>`s for NG-style State → LGA addressing (Plan-14 Task 7).
 * States load from `/api/regions?country=<CC>` on mount/country change; picking a
 * state loads its children from `/api/regions?parent=<id>` and clears any
 * previously-picked area (an old area id would no longer belong to the new state).
 * Fully controlled: this component holds no address-form state of its own, it only
 * emits ids via `onChange` — AddressStep owns the actual form values. */
export function RegionSelect({ country, stateValue, areaValue, onChange, labels }: RegionSelectProps) {
  const [states, setStates] = useState<Region[] | null>(null);
  const [areas, setAreas] = useState<Region[] | null>(null);
  const [areasLoading, setAreasLoading] = useState(false);

  const stateLabel = labels?.state ?? "State";
  const areaLabel = labels?.area ?? "LGA";

  // Fetches states for the (locked) shopping country. All setState calls happen
  // after the awaited fetch, not synchronously in the effect body, so this doesn't
  // trip react-hooks/set-state-in-effect (same shape as SignInStep's mount check).
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

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div>
        <label htmlFor="region-state" className="mb-1 block text-sm font-medium">
          {stateLabel}
        </label>
        <select
          id="region-state"
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
      <div>
        <label htmlFor="region-area" className="mb-1 block text-sm font-medium">
          {areaLabel}
        </label>
        <select
          id="region-area"
          value={areaValue ?? ""}
          onChange={handleAreaChange}
          disabled={!stateValue || areasLoading}
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
    </div>
  );
}
