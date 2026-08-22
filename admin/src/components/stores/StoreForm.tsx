"use client";

/**
 * Add or edit one shop in the store directory (Plan-42).
 *
 * ── THE CASCADE IS FILTERED FROM ONE FLAT LIST ──────────────────────────────────────
 *
 * `/admin/regions/` sends every region — 37 NG states and their 774 LGAs, plus GB/US/CA
 * — flat and unpaginated, and the page loads it once. Narrowing it here is a filter over
 * an array the browser already holds, which is why changing country or state is
 * instant and needs no request. The same list feeds the filter bar above the table, so
 * the form and the filter can never disagree about which LGAs exist.
 *
 * ── THE THIRD FIELD IS EITHER AN LGA OR A CITY, NEVER BOTH ──────────────────────────
 *
 * NG states have LGAs; GB/US/CA level-1 regions have none. The serializer enforces
 * exactly this — an LGA where the state has them, a city where it does not, and it
 * refuses an LGA for a state with no districts — so rendering both fields would offer
 * the operator a way to fail. Whichever one applies is the one on screen.
 *
 * ── "SAVE ANYWAY" IS THE ONLY WAY PAST A DUPLICATE ──────────────────────────────────
 *
 * A 409 carrying look-alike rows is a question, not a failure, and it is answered by a
 * SECOND SUBMIT with `confirm_duplicate` — the flag is never pre-set, and editing any
 * field after the warning drops it, so the operator can only confirm the exact thing
 * they were warned about.
 */
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  saveStoreAction,
  type StoreActionState,
  type StoreInput,
} from "@/app/(shell)/find-stores/actions";
import type { CountryRef } from "@/lib/reference";
import type { RegionRow } from "@/lib/regions";
import { STORE_TYPES, storeTypeLabel, type DuplicateHint, type StoreRow } from "@/lib/stores";

const FIELD =
  "mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

type Draft = Omit<StoreInput, "id" | "confirm_duplicate">;

const EMPTY: Draft = {
  name: "",
  store_type: "distributor",
  country: null,
  state_region: null,
  area_region: null,
  city_text: "",
  address: "",
  latitude: "",
  longitude: "",
  phone: "",
  phone_alt: "",
  whatsapp_phone: "",
  opening_hours: "",
  notes: "",
  is_active: true,
};

function draftFrom(row: StoreRow): Draft {
  return {
    name: row.name,
    store_type: row.store_type,
    // `core.Country`'s primary key IS the ISO code, so the row's `country` is already
    // the value the serializer wants back.
    country: row.country,
    state_region: row.state_region,
    area_region: row.area_region,
    city_text: row.city_text,
    address: row.address,
    latitude: row.latitude ?? "",
    longitude: row.longitude ?? "",
    phone: row.phone,
    phone_alt: row.phone_alt,
    whatsapp_phone: row.whatsapp_phone,
    opening_hours: row.opening_hours,
    notes: row.notes,
    is_active: row.is_active,
  };
}

export function StoreForm({
  row,
  countries,
  regions,
  onDone,
  onCancel,
}: {
  /** null = create. */
  row: StoreRow | null;
  countries: CountryRef[];
  regions: RegionRow[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const router = useRouter();
  const [draft, setDraft] = useState<Draft>(row ? draftFrom(row) : EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [duplicates, setDuplicates] = useState<DuplicateHint[] | null>(null);
  const [duplicateMessage, setDuplicateMessage] = useState<string>("");
  const [saving, setSaving] = useState(false);

  const country = countries.find((c) => c.code === draft.country) ?? null;
  const stateLabel = country?.state_label || "State";
  const areaLabel = country?.area_label || "Area";

  const states = useMemo(
    () =>
      regions
        .filter((r) => r.level === "state" && r.country_code === country?.code)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [regions, country?.code],
  );
  const areas = useMemo(
    () =>
      regions
        .filter((r) => r.level === "area" && r.parent === draft.state_region)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [regions, draft.state_region],
  );
  const stateHasAreas = areas.length > 0;

  /** Any edit invalidates a standing duplicate warning — the operator can only ever
   *  confirm the exact rows they were shown. */
  function set<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((d) => ({ ...d, [key]: value }));
    setDuplicates(null);
  }

  function pickCountry(raw: string) {
    // The chain below is invalid the moment the country changes: a Lagos state id under
    // Ghana is exactly the mismatch the serializer refuses.
    setDraft((d) => ({
      ...d,
      country: raw || null,
      state_region: null,
      area_region: null,
      city_text: "",
    }));
    setDuplicates(null);
  }

  function pickState(raw: string) {
    const id = raw === "" ? null : Number(raw);
    setDraft((d) => ({ ...d, state_region: id, area_region: null }));
    setDuplicates(null);
  }

  async function submit(confirmDuplicate: boolean) {
    setSaving(true);
    setErrors({});
    setMessage(null);
    try {
      const result: StoreActionState = await saveStoreAction({
        id: row?.id ?? null,
        ...draft,
        // A city is meaningless where an LGA was chosen, and vice versa. Sending the
        // stale one would file a shop under a district it is not in.
        area_region: stateHasAreas ? draft.area_region : null,
        city_text: stateHasAreas ? "" : draft.city_text,
        confirm_duplicate: confirmDuplicate,
      });
      if (result.duplicates) {
        setDuplicates(result.duplicates);
        setDuplicateMessage(result.duplicateMessage ?? "");
      } else if (result.fieldErrors) {
        setErrors(result.fieldErrors);
      } else if (result.message) {
        setMessage(result.message);
      } else {
        onDone();
        router.refresh();
      }
    } catch {
      setMessage("Something went wrong saving this store.");
    } finally {
      setSaving(false);
    }
  }

  const err = (key: string) =>
    errors[key] ? <p className="mt-1 text-xs text-danger">{errors[key]}</p> : null;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void submit(false);
      }}
      className="rounded-[var(--radius-card)] border border-accent/40 bg-surface p-4"
    >
      <h2 className="text-sm font-semibold">
        {row ? `Edit ${row.name}` : "Add a store"}
      </h2>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="block text-xs text-muted">
          Country
          <select
            className={FIELD}
            value={draft.country ?? ""}
            onChange={(e) => pickCountry(e.target.value)}
            required
          >
            <option value="">Select…</option>
            {countries.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </select>
          {err("country")}
        </label>

        <label className="block text-xs text-muted">
          {stateLabel}
          <select
            className={FIELD}
            value={draft.state_region ?? ""}
            onChange={(e) => pickState(e.target.value)}
            disabled={!draft.country}
            required
          >
            <option value="">
              {draft.country ? "Select…" : `Pick a country first`}
            </option>
            {states.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          {err("state_region")}
        </label>

        {/* Either the LGA picker or the free-text town — see the module docstring. */}
        {stateHasAreas ? (
          <label className="block text-xs text-muted">
            {areaLabel}
            <select
              className={FIELD}
              value={draft.area_region ?? ""}
              onChange={(e) => set("area_region", e.target.value ? Number(e.target.value) : null)}
              required
            >
              <option value="">Select…</option>
              {areas.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            {err("area_region")}
          </label>
        ) : (
          <label className="block text-xs text-muted">
            Town or city
            <input
              className={FIELD}
              value={draft.city_text}
              onChange={(e) => set("city_text", e.target.value)}
              disabled={!draft.state_region}
              placeholder="Croydon"
            />
            {err("city_text")}
          </label>
        )}

        <label className="block text-xs text-muted sm:col-span-2">
          Store name
          <input
            className={FIELD}
            value={draft.name}
            onChange={(e) => set("name", e.target.value)}
            maxLength={120}
            placeholder="Toke Ogudu Store"
            required
          />
          {err("name")}
        </label>

        <label className="block text-xs text-muted">
          Store type
          <select
            className={FIELD}
            value={draft.store_type}
            onChange={(e) => set("store_type", e.target.value)}
          >
            {STORE_TYPES.map((t) => (
              <option key={t} value={t}>
                {storeTypeLabel(t)}
              </option>
            ))}
          </select>
          {err("store_type")}
        </label>

        <label className="block text-xs text-muted lg:col-span-3">
          Street address
          <input
            className={FIELD}
            value={draft.address}
            onChange={(e) => set("address", e.target.value)}
            maxLength={300}
            placeholder="12 Hassan Balogun Street, Isheri-Olofin, Ikotun"
            required
          />
          {err("address")}
        </label>

        <label className="block text-xs text-muted">
          Phone — customers call this
          <input
            className={FIELD}
            value={draft.phone}
            onChange={(e) => set("phone", e.target.value)}
            placeholder="+2348023900964"
            required
          />
          {err("phone")}
        </label>

        <label className="block text-xs text-muted">
          Second phone (optional)
          <input
            className={FIELD}
            value={draft.phone_alt}
            onChange={(e) => set("phone_alt", e.target.value)}
            placeholder="+2348012345678"
          />
          {err("phone_alt")}
        </label>

        <label className="block text-xs text-muted">
          WhatsApp (optional)
          <input
            className={FIELD}
            value={draft.whatsapp_phone}
            onChange={(e) => set("whatsapp_phone", e.target.value)}
            placeholder="+2348023900964"
          />
          {err("whatsapp_phone")}
        </label>

        <label className="block text-xs text-muted sm:col-span-2">
          Opening hours (optional)
          <input
            className={FIELD}
            value={draft.opening_hours}
            onChange={(e) => set("opening_hours", e.target.value)}
            maxLength={160}
            placeholder="Mon–Sat, 9am – 7pm · Closed Sundays"
          />
          {err("opening_hours")}
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label className="block text-xs text-muted">
            Latitude (optional)
            <input
              className={FIELD}
              value={draft.latitude}
              onChange={(e) => set("latitude", e.target.value)}
              placeholder="6.601838"
            />
            {err("latitude")}
          </label>
          <label className="block text-xs text-muted">
            Longitude
            <input
              className={FIELD}
              value={draft.longitude}
              onChange={(e) => set("longitude", e.target.value)}
              placeholder="3.351486"
            />
            {err("longitude")}
          </label>
        </div>

        <label className="block text-xs text-muted lg:col-span-2">
          Staff notes (never shown to customers)
          <input
            className={FIELD}
            value={draft.notes}
            onChange={(e) => set("notes", e.target.value)}
            maxLength={300}
            placeholder="Owner: Mrs Adebayo. Restocks fortnightly."
          />
          {err("notes")}
        </label>

        <label className="flex items-end gap-2 text-xs text-muted">
          <input
            type="checkbox"
            checked={draft.is_active}
            onChange={(e) => set("is_active", e.target.checked)}
            className="mb-1.5 size-4 accent-[var(--color-accent)]"
          />
          <span className="mb-1">Listed on the website</span>
        </label>
      </div>

      {/* A pin is optional and imprecise addresses are the norm here, so this says what
          the coordinate fields actually buy rather than leaving them unexplained. */}
      <p className="mt-3 text-xs text-muted">
        With a latitude and longitude, &ldquo;Get directions&rdquo; points at the exact
        spot. Without one it searches the address text, which lands a customer in the
        right neighbourhood rather than at the door.
      </p>

      {duplicates && (
        <DuplicateWarning
          hints={duplicates}
          message={duplicateMessage}
          saving={saving}
          onConfirm={() => void submit(true)}
        />
      )}

      {message && (
        <p role="alert" className="mt-3 rounded border border-danger/30 bg-danger/5 p-2 text-xs text-danger">
          {message}
        </p>
      )}

      <div className="mt-4 flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
        >
          {saving ? "Saving…" : row ? "Save changes" : "Add store"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

/** The 409's rows, and the one button that gets past them. An empty `hints` list means
 *  the database's unique index refused the save outright — there is nothing to confirm,
 *  so no override is offered. */
function DuplicateWarning({
  hints,
  message,
  saving,
  onConfirm,
}: {
  hints: DuplicateHint[];
  message: string;
  saving: boolean;
  onConfirm: () => void;
}) {
  return (
    <div
      role="alert"
      className="mt-3 rounded border border-warn/40 bg-warn/5 p-3 text-xs text-warn"
    >
      <p className="font-medium">{message}</p>
      {hints.length > 0 && (
        <>
          <ul className="mt-2 space-y-1">
            {hints.map((hint, i) => (
              <li key={`${hint.kind}-${hint.id ?? i}`}>
                <span className="font-medium">{hint.label}</span>
                {hint.detail && <span className="text-muted"> — {hint.detail}</span>}
                <span className="text-muted"> ({hint.reason} matches)</span>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={onConfirm}
            disabled={saving}
            className="mt-3 rounded border border-warn px-3 py-1.5 font-medium hover:bg-warn/10 disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save anyway — this is a different shop"}
          </button>
        </>
      )}
    </div>
  );
}
