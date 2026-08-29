"use client";

/**
 * The partner's rate card (Plan-39): every zone row, grouped by state then LGA, with
 * inline add / edit / delete. All traffic goes through the partner BFF proxy
 * (`/api/partner/...`), which attaches the httpOnly partner cookies server-side;
 * a 401 from it means the session died — the only correct move is back to the login.
 *
 * The form mirrors the doc columns the partner manages (Hammed's ruling): LGA,
 * LCDA, Major Locations & Landmarks, Dispatch Zone, Rate — widened 2026-08 at
 * BrandnPack's request into a state → LGA cascade so coverage outside Lagos can be
 * added, plus the delivery-day estimate customers see (the old hidden 1–3 default
 * was a Lagos number). A row without a rate is badged "needs a price" and is never
 * offered at checkout, so leaving the rate empty is a safe way to stage a new area.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { PartnerMe, PartnerRegionOption, PartnerZoneRow } from "@/lib/partners";
import { formatNaira } from "@/lib/partners";

interface ZoneDraft {
  state: string; // select value; "" = unchosen — never sent, it only scopes the LGA list
  lga_region: string; // select value; "" = unchosen
  lcda_name: string;
  areas_covered: string;
  dispatch_zone: string;
  price: string; // "" = no price yet
  min_days: string;
  max_days: string;
  is_active: boolean;
}

const EMPTY_DRAFT: ZoneDraft = {
  state: "", lga_region: "", lcda_name: "", areas_covered: "", dispatch_zone: "",
  price: "", min_days: "1", max_days: "3", is_active: true,
};

function draftFrom(row: PartnerZoneRow): ZoneDraft {
  return {
    state: String(row.state_id),
    lga_region: String(row.lga_region),
    lcda_name: row.lcda_name,
    areas_covered: row.areas_covered,
    dispatch_zone: row.dispatch_zone,
    price: row.price === null ? "" : String(Number(row.price)),
    min_days: String(row.min_days),
    max_days: String(row.max_days),
    is_active: row.is_active,
  };
}

function bodyFrom(draft: ZoneDraft): Record<string, unknown> {
  return {
    lga_region: Number(draft.lga_region),
    lcda_name: draft.lcda_name.trim(),
    areas_covered: draft.areas_covered.trim(),
    dispatch_zone: draft.dispatch_zone.trim(),
    price: draft.price.trim() === "" ? null : draft.price.trim(),
    min_days: Number(draft.min_days),
    max_days: Number(draft.max_days),
    is_active: draft.is_active,
  };
}

/** A whole positive day count, or null — "2.5" and "0" both fail. */
function dayValue(raw: string): number | null {
  const n = Number(raw.trim());
  return Number.isInteger(n) && n >= 1 ? n : null;
}

async function api(path: string, init?: RequestInit): Promise<Response> {
  const res = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (res.status === 401) {
    // The BFF proxy already cleared the dead cookies; finish the sign-out visibly.
    window.location.assign("/partner/login");
    throw new Error("signed out");
  }
  return res;
}

function firstError(data: unknown): string {
  if (data && typeof data === "object") {
    for (const value of Object.values(data as Record<string, unknown>)) {
      const first = Array.isArray(value) ? value[0] : value;
      if (typeof first === "string") return first;
    }
  }
  return "That could not be saved — please check the row and try again.";
}

export function PartnerRateCard() {
  const [me, setMe] = useState<PartnerMe | null>(null);
  const [states, setStates] = useState<PartnerRegionOption[]>([]);
  const [zones, setZones] = useState<PartnerZoneRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // LGA lists arrive per state as the partner picks one; fetched once each, kept.
  const [lgasByState, setLgasByState] = useState<Record<string, PartnerRegionOption[]>>({});

  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState<ZoneDraft>(EMPTY_DRAFT);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [meRes, stateRes, zoneRes] = await Promise.all([
        api("/api/partner/me"), api("/api/partner/states"), api("/api/partner/zones"),
      ]);
      if (!meRes.ok || !stateRes.ok || !zoneRes.ok) {
        setLoadError("Your rate card could not be loaded — please refresh.");
        return;
      }
      setMe(await meRes.json());
      setStates(await stateRes.json());
      setZones(await zoneRes.json());
      setLoadError(null);
    } catch (e) {
      if ((e as Error).message === "signed out") return;
      setLoadError("Your rate card could not be loaded — please refresh.");
    }
  }, []);

  // Mount fetch. `react-hooks/set-state-in-effect` reports the call below as a
  // synchronous setState, which it is not: `reload` is ASYNC and every setState in it
  // runs after `await Promise.all([...])`, i.e. in a later microtask, so none of the
  // render cascade the rule exists to prevent can happen here. The only other way to
  // silence it is to wrap the call in an async IIFE — behaviourally identical to this
  // line, and exactly the sort of thing a future reader would helpfully "simplify"
  // straight back into a build failure. The reason is recorded here instead.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- see above
    void reload();
  }, [reload]);

  const loadLgas = useCallback(async (stateId: string) => {
    if (!stateId) return;
    try {
      const res = await api(`/api/partner/lgas?state=${encodeURIComponent(stateId)}`);
      if (!res.ok) return; // the LGA select stays in its "loading" state; re-picking retries
      const options: PartnerRegionOption[] = await res.json();
      setLgasByState((m) => (m[stateId] ? m : { ...m, [stateId]: options }));
    } catch {
      /* a dropped fetch leaves the cache empty — picking the state again retries */
    }
  }, []);

  // state → LGA groups → rows, states and LGAs both alphabetical.
  const grouped = useMemo(() => {
    const byState = new Map<string, Map<string, PartnerZoneRow[]>>();
    for (const z of zones ?? []) {
      const byLga = byState.get(z.state_name) ?? new Map<string, PartnerZoneRow[]>();
      const list = byLga.get(z.lga_name) ?? [];
      list.push(z);
      byLga.set(z.lga_name, list);
      byState.set(z.state_name, byLga);
    }
    return [...byState.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([stateName, byLga]) => [
        stateName,
        [...byLga.entries()].sort(([a], [b]) => a.localeCompare(b)),
      ] as const);
  }, [zones]);

  function startAdd() {
    setAdding(true);
    setEditingId(null);
    setDraft(EMPTY_DRAFT);
    setFormError(null);
  }

  function startEdit(row: PartnerZoneRow) {
    setEditingId(row.id);
    setAdding(false);
    setDraft(draftFrom(row));
    setFormError(null);
    void loadLgas(String(row.state_id));
  }

  function cancelForm() {
    setAdding(false);
    setEditingId(null);
    setFormError(null);
  }

  function pickState(stateId: string) {
    // Changing state invalidates the LGA choice — the old one belongs elsewhere.
    setDraft((d) => ({ ...d, state: stateId, lga_region: "" }));
    void loadLgas(stateId);
  }

  async function submitDraft() {
    if (!draft.state) {
      setFormError("Choose the state this area is in.");
      return;
    }
    if (!draft.lga_region) {
      setFormError("Choose the LGA this area belongs to.");
      return;
    }
    if (!draft.lcda_name.trim() || !draft.areas_covered.trim()) {
      setFormError("The LCDA name and the locations covered are both required.");
      return;
    }
    const minDays = dayValue(draft.min_days);
    const maxDays = dayValue(draft.max_days);
    if (minDays === null || maxDays === null || minDays > maxDays) {
      setFormError("Delivery days must be whole numbers of at least 1, quickest first.");
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      const res = editingId === null
        ? await api("/api/partner/zones", { method: "POST", body: JSON.stringify(bodyFrom(draft)) })
        : await api(`/api/partner/zones/${editingId}`, {
            method: "PATCH", body: JSON.stringify(bodyFrom(draft)),
          });
      if (!res.ok) {
        setFormError(firstError(await res.json().catch(() => null)));
        return;
      }
      cancelForm();
      await reload();
    } catch (e) {
      if ((e as Error).message !== "signed out") {
        setFormError("Saving failed — please check your connection and try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function removeRow(row: PartnerZoneRow) {
    const ok = window.confirm(
      `Delete ${row.lcda_name} (${row.lga_name}, ${row.state_name})? Customers will stop being offered it immediately.`,
    );
    if (!ok) return;
    try {
      const res = await api(`/api/partner/zones/${row.id}`, { method: "DELETE" });
      if (res.ok || res.status === 204) await reload();
    } catch {
      /* a failed delete leaves the row visible — nothing to do */
    }
  }

  if (loadError) {
    return (
      <p role="alert" className="rounded-[var(--radius-card)] border border-danger/30 bg-danger/5 p-4 text-sm text-danger">
        {loadError}
      </p>
    );
  }
  if (zones === null) {
    return <p className="text-sm text-muted">Loading your rate card…</p>;
  }

  const lgaOptions = draft.state ? lgasByState[draft.state] : undefined;

  const form = (
    <div className="rounded-[var(--radius-card)] border border-accent/40 bg-accent/5 p-4">
      <p className="text-sm font-semibold">
        {editingId === null ? "Add a delivery area" : "Edit delivery area"}
      </p>
      {formError && (
        <p role="alert" className="mt-2 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">
          {formError}
        </p>
      )}
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="font-medium">State</span>
          <select
            value={draft.state}
            onChange={(e) => pickState(e.target.value)}
            className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
          >
            <option value="">Choose a state…</option>
            {states.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="font-medium">LGA</span>
          <select
            value={draft.lga_region}
            onChange={(e) => setDraft({ ...draft, lga_region: e.target.value })}
            disabled={!draft.state}
            className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent disabled:opacity-60"
          >
            <option value="">
              {!draft.state
                ? "Choose a state first…"
                : lgaOptions === undefined
                  ? "Loading LGAs…"
                  : "Choose an LGA…"}
            </option>
            {(lgaOptions ?? []).map((l) => (
              <option key={l.id} value={l.id}>{l.name}</option>
            ))}
          </select>
        </label>
        <label className="block text-sm sm:col-span-2">
          <span className="font-medium">LCDA</span>
          <input
            value={draft.lcda_name}
            onChange={(e) => setDraft({ ...draft, lcda_name: e.target.value })}
            placeholder="e.g. Ikorodu Central"
            className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
          />
        </label>
        <label className="block text-sm sm:col-span-2">
          <span className="font-medium">Major locations &amp; landmarks</span>
          <input
            value={draft.areas_covered}
            onChange={(e) => setDraft({ ...draft, areas_covered: e.target.value })}
            placeholder="e.g. Ikorodu Town, Garage, Benson"
            className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
          />
          <span className="mt-1 block text-xs text-muted">
            Customers see this as “Areas covered” when choosing delivery.
          </span>
        </label>
        <label className="block text-sm">
          <span className="font-medium">Dispatch zone</span>
          <input
            value={draft.dispatch_zone}
            onChange={(e) => setDraft({ ...draft, dispatch_zone: e.target.value })}
            placeholder="e.g. Zone 6 - Northeast Suburbs"
            className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium">Rate (₦)</span>
          <input
            type="number"
            min={1}
            step={100}
            value={draft.price}
            onChange={(e) => setDraft({ ...draft, price: e.target.value })}
            placeholder="e.g. 4000"
            className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
          />
          <span className="mt-1 block text-xs text-muted">
            Leave empty to keep the area hidden until you have a price.
          </span>
        </label>
        <div className="block text-sm sm:col-span-2">
          <span className="font-medium">Delivery time (days)</span>
          <div className="mt-1 flex items-center gap-2">
            <input
              type="number"
              min={1}
              max={30}
              value={draft.min_days}
              onChange={(e) => setDraft({ ...draft, min_days: e.target.value })}
              aria-label="Quickest delivery, in days"
              className="w-20 rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
            />
            <span className="text-muted">to</span>
            <input
              type="number"
              min={1}
              max={30}
              value={draft.max_days}
              onChange={(e) => setDraft({ ...draft, max_days: e.target.value })}
              aria-label="Longest delivery, in days"
              className="w-20 rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
            />
          </div>
          <span className="mt-1 block text-xs text-muted">
            Shown to customers at checkout — set a realistic range for areas outside Lagos.
          </span>
        </div>
        <label className="flex items-center gap-2 text-sm sm:col-span-2">
          <input
            type="checkbox"
            checked={draft.is_active}
            onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })}
          />
          <span>Offer this area to customers (needs a rate to appear)</span>
        </label>
      </div>
      <div className="mt-4 flex gap-2">
        <button
          type="button"
          onClick={submitDraft}
          disabled={busy}
          className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-accent-strong disabled:opacity-60"
        >
          {busy ? "Saving…" : editingId === null ? "Add area" : "Save changes"}
        </button>
        <button
          type="button"
          onClick={cancelForm}
          disabled={busy}
          className="rounded-md border border-line px-4 py-2 text-sm transition-colors hover:border-accent/60"
        >
          Cancel
        </button>
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted">
          {me ? `Signed in as ${me.name} (${me.email}). ` : ""}
          {zones.length} areas — {zones.filter((z) => z.is_active && z.price !== null).length} live at checkout.
        </p>
        {!adding && editingId === null && (
          <button
            type="button"
            onClick={startAdd}
            className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-accent-strong"
          >
            Add delivery area
          </button>
        )}
      </div>

      {adding && form}

      {grouped.map(([stateName, lgaGroups]) => (
        <section key={stateName}>
          <h2 className="text-base font-semibold tracking-tight">{stateName}</h2>
          {lgaGroups.map(([lgaName, rows]) => (
            <div key={lgaName} className="mt-3">
              <h3 className="text-sm font-semibold tracking-tight text-muted">{lgaName}</h3>
              <div className="mt-2 space-y-2">
                {rows.map((row) =>
                  editingId === row.id ? (
                    <div key={row.id}>{form}</div>
                  ) : (
                    <div
                      key={row.id}
                      className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-[var(--radius-card)] border border-line bg-surface px-4 py-3 text-sm"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="font-medium">
                          {row.lcda_name}
                          {(!row.is_active || row.price === null) && (
                            <span className="ml-2 rounded-full border border-warn/40 bg-warn/10 px-2 py-0.5 text-xs text-warn">
                              {row.price === null ? "needs a price" : "hidden"}
                            </span>
                          )}
                        </p>
                        <p className="mt-0.5 truncate text-muted">{row.areas_covered}</p>
                      </div>
                      <span className="text-muted">{row.dispatch_zone}</span>
                      <span className="text-muted">
                        {row.min_days === row.max_days
                          ? `${row.min_days} day${row.min_days === 1 ? "" : "s"}`
                          : `${row.min_days}–${row.max_days} days`}
                      </span>
                      <span className="w-20 text-right font-semibold">{formatNaira(row.price)}</span>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => startEdit(row)}
                          className="rounded-md border border-line px-2.5 py-1 text-xs transition-colors hover:border-accent/60"
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          onClick={() => removeRow(row)}
                          className="rounded-md border border-danger/30 px-2.5 py-1 text-xs text-danger transition-colors hover:bg-danger/5"
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  ),
                )}
              </div>
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
