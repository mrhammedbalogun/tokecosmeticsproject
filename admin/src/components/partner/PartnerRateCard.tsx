"use client";

/**
 * The partner's rate card (Plan-39): every zone row, grouped by LGA, with inline
 * add / edit / delete. All traffic goes through the partner BFF proxy
 * (`/api/partner/...`), which attaches the httpOnly partner cookies server-side;
 * a 401 from it means the session died — the only correct move is back to the login.
 *
 * The form mirrors the five doc columns the partner manages (Hammed's ruling): LGA,
 * LCDA, Major Locations & Landmarks, Dispatch Zone, Rate. A row without a rate is
 * badged "needs a price" and is never offered at checkout, so leaving the rate empty
 * is a safe way to stage a new area.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { PartnerLgaOption, PartnerMe, PartnerZoneRow } from "@/lib/partners";
import { formatNaira } from "@/lib/partners";

interface ZoneDraft {
  lga_region: string; // select value; "" = unchosen
  lcda_name: string;
  areas_covered: string;
  dispatch_zone: string;
  price: string; // "" = no price yet
  is_active: boolean;
}

const EMPTY_DRAFT: ZoneDraft = {
  lga_region: "", lcda_name: "", areas_covered: "", dispatch_zone: "",
  price: "", is_active: true,
};

function draftFrom(row: PartnerZoneRow): ZoneDraft {
  return {
    lga_region: String(row.lga_region),
    lcda_name: row.lcda_name,
    areas_covered: row.areas_covered,
    dispatch_zone: row.dispatch_zone,
    price: row.price === null ? "" : String(Number(row.price)),
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
    is_active: draft.is_active,
  };
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
  const [lgas, setLgas] = useState<PartnerLgaOption[]>([]);
  const [zones, setZones] = useState<PartnerZoneRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState<ZoneDraft>(EMPTY_DRAFT);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [meRes, lgaRes, zoneRes] = await Promise.all([
        api("/api/partner/me"), api("/api/partner/lgas"), api("/api/partner/zones"),
      ]);
      if (!meRes.ok || !lgaRes.ok || !zoneRes.ok) {
        setLoadError("Your rate card could not be loaded — please refresh.");
        return;
      }
      setMe(await meRes.json());
      setLgas(await lgaRes.json());
      setZones(await zoneRes.json());
      setLoadError(null);
    } catch (e) {
      if ((e as Error).message === "signed out") return;
      setLoadError("Your rate card could not be loaded — please refresh.");
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const grouped = useMemo(() => {
    const byLga = new Map<string, PartnerZoneRow[]>();
    for (const z of zones ?? []) {
      const list = byLga.get(z.lga_name) ?? [];
      list.push(z);
      byLga.set(z.lga_name, list);
    }
    return [...byLga.entries()].sort(([a], [b]) => a.localeCompare(b));
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
  }

  function cancelForm() {
    setAdding(false);
    setEditingId(null);
    setFormError(null);
  }

  async function submitDraft() {
    if (!draft.lga_region) {
      setFormError("Choose the LGA this area belongs to.");
      return;
    }
    if (!draft.lcda_name.trim() || !draft.areas_covered.trim()) {
      setFormError("The LCDA name and the locations covered are both required.");
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
      `Delete ${row.lcda_name} (${row.lga_name})? Customers will stop being offered it immediately.`,
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
          <span className="font-medium">LGA</span>
          <select
            value={draft.lga_region}
            onChange={(e) => setDraft({ ...draft, lga_region: e.target.value })}
            className="mt-1 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
          >
            <option value="">Choose an LGA…</option>
            {lgas.map((l) => (
              <option key={l.id} value={l.id}>{l.name}</option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
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

      {grouped.map(([lgaName, rows]) => (
        <section key={lgaName}>
          <h2 className="text-sm font-semibold tracking-tight">{lgaName}</h2>
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
        </section>
      ))}
    </div>
  );
}
