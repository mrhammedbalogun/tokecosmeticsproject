"use client";

/**
 * Pickup origins (Plan-34): the Toke locations GIG riders collect from.
 *
 * Every quote picks the nearest ACTIVE origin to the customer, so the pin here
 * prices real orders and is where a rider physically drives — the form says so
 * out loud instead of trusting that a coordinate field looks important. Same
 * interaction grammar as DeliveryOptions: collapsed rows, expand-in-place
 * (hidden not unmounted, so a collapse can't destroy edits), two-step inline
 * delete. Deactivating the LAST active origin gets a notice, not a block: the
 * backend falls back to the built-in Ogudu env sender, so it's safe — but the
 * operator should know that's what they're choosing.
 */
import { startTransition, useState } from "react";
import { useRouter } from "next/navigation";
import {
  deleteSenderLocationAction,
  saveSenderLocationAction,
  type SenderLocationRow,
} from "@/app/(shell)/deliveries/pickup-locations/actions";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

const EMPTY: SenderLocationRow = {
  id: 0,
  name: "",
  phone: "",
  address: "",
  locality: "",
  latitude: "",
  longitude: "",
  state: "",
  lga: "",
  customer_pickup: false,
  state_region: null,
  is_active: true,
};

/** The canonical NG states (core.Region pks) the State dropdown offers. */
export interface StateOption {
  id: number;
  name: string;
}

function OriginForm({
  row,
  states,
  isLastActive,
  onDone,
}: {
  row: SenderLocationRow | null; // null = create
  states: StateOption[];
  isLastActive: boolean;
  onDone: () => void;
}) {
  const router = useRouter();
  const [draft, setDraft] = useState<SenderLocationRow>(row ?? EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const set = (key: keyof SenderLocationRow) => (value: string | boolean) =>
    setDraft((d) => ({ ...d, [key]: value }));

  // The dropdown writes BOTH columns: `state_region` is what customer store pickup
  // matches on, `state` keeps the row's display label in step with it.
  const setStateRegion = (raw: string) => {
    const id = raw === "" ? null : Number(raw);
    const name = states.find((s) => s.id === id)?.name ?? "";
    setDraft((d) => ({ ...d, state_region: id, state: name }));
  };

  async function save() {
    setSaving(true);
    setErrors({});
    setMessage(null);
    try {
      const result = await saveSenderLocationAction({
        id: row ? row.id : null,
        name: draft.name,
        phone: draft.phone,
        address: draft.address,
        locality: draft.locality,
        latitude: draft.latitude,
        longitude: draft.longitude,
        state: draft.state,
        lga: draft.lga,
        customer_pickup: draft.customer_pickup,
        state_region: draft.state_region,
        is_active: draft.is_active,
      });
      if (result.fieldErrors) setErrors(result.fieldErrors);
      else if (result.message) setMessage(result.message);
      else {
        onDone();
        startTransition(() => router.refresh());
      }
    } catch {
      setMessage("Something went wrong saving this origin.");
    } finally {
      setSaving(false);
    }
  }

  const err = (key: string) =>
    errors[key] ? <p className="mt-1 text-xs text-warn">{errors[key]}</p> : null;

  return (
    <div className="mt-3 grid gap-3 border-t border-line pt-3 sm:grid-cols-2">
      <label className="block text-sm">
        <span className="text-muted">Name (shown to staff on orders)</span>
        <input
          className={FIELD}
          value={draft.name}
          onChange={(e) => set("name")(e.target.value)}
          placeholder="Kubwa (Abuja)"
        />
        {err("name")}
      </label>
      <label className="block text-sm">
        <span className="text-muted">Pickup phone — GIG calls this number</span>
        <input
          className={FIELD}
          value={draft.phone}
          onChange={(e) => set("phone")(e.target.value)}
          placeholder="+2347074800702"
        />
        {err("phone")}
      </label>
      <label className="block text-sm sm:col-span-2">
        <span className="text-muted">Street address — printed on the waybill</span>
        <input
          className={FIELD}
          value={draft.address}
          onChange={(e) => set("address")(e.target.value)}
        />
        {err("address")}
      </label>
      <label className="block text-sm">
        <span className="text-muted">Locality (area name)</span>
        <input
          className={FIELD}
          value={draft.locality}
          onChange={(e) => set("locality")(e.target.value)}
          placeholder="Kubwa"
        />
        {err("locality")}
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className="block text-sm">
          <span className="text-muted">Latitude</span>
          <input
            className={FIELD}
            value={draft.latitude}
            onChange={(e) => set("latitude")(e.target.value)}
            placeholder="9.152000"
          />
          {err("latitude")}
        </label>
        <label className="block text-sm">
          <span className="text-muted">Longitude</span>
          <input
            className={FIELD}
            value={draft.longitude}
            onChange={(e) => set("longitude")(e.target.value)}
            placeholder="7.324000"
          />
          {err("longitude")}
        </label>
      </div>
      <p className="text-xs text-muted sm:col-span-2">
        The pin prices every quote and is where the rider drives — it must be the shop
        itself, not the neighbourhood. In Google Maps, right-click the shop and click the
        coordinates to copy them.
      </p>
      <div className="grid grid-cols-2 gap-3 sm:col-span-2">
        <label className="block text-sm">
          <span className="text-muted">State</span>
          <select
            className={FIELD}
            value={draft.state_region === null ? "" : String(draft.state_region)}
            onChange={(e) => setStateRegion(e.target.value)}
          >
            <option value="">— pick a state —</option>
            {states.map((s) => (
              <option key={s.id} value={String(s.id)}>
                {s.name}
              </option>
            ))}
          </select>
          {err("state_region")}
          {err("state")}
        </label>
        <label className="block text-sm">
          <span className="text-muted">LGA (display only)</span>
          <input
            className={FIELD}
            value={draft.lga}
            onChange={(e) => set("lga")(e.target.value)}
            placeholder="Bwari"
          />
          {err("lga")}
        </label>
      </div>
      <p className="text-xs text-muted sm:col-span-2">
        GIG routing still follows the pin, never these labels. The state DOES matter for
        customer store pickup below — customers see this location when their delivery
        address is in the same state, whatever their LGA.
      </p>
      <label className="flex items-center gap-2 text-sm sm:col-span-2">
        <input
          type="checkbox"
          checked={draft.customer_pickup}
          onChange={(e) => set("customer_pickup")(e.target.checked)}
        />
        <span>
          Customer pickup store — shows at checkout as &ldquo;Pickup at Toke Cosmetics
          Store&rdquo; (free) for customers in this state
        </span>
      </label>
      {draft.customer_pickup && draft.state_region === null && (
        <p className="rounded border border-warn/30 bg-warn/5 p-2 text-xs text-warn sm:col-span-2">
          Pick the store&rsquo;s state above — customers are matched by state, so without
          one this store shows to nobody.
        </p>
      )}
      <label className="flex items-center gap-2 text-sm sm:col-span-2">
        <input
          type="checkbox"
          checked={draft.is_active}
          onChange={(e) => set("is_active")(e.target.checked)}
        />
        <span>Ships orders (nearest active origin wins)</span>
      </label>
      {row && isLastActive && !draft.is_active && (
        <p className="rounded border border-warn/30 bg-warn/5 p-2 text-xs text-warn sm:col-span-2">
          This is the last active origin. Checkout keeps working — quotes fall back to the
          built-in Ogudu Mall sender — but no other location will be used until one is
          reactivated.
        </p>
      )}
      {message && <p className="text-sm text-warn sm:col-span-2">{message}</p>}
      <div className="flex gap-2 sm:col-span-2">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          {saving ? "Saving…" : row ? "Save origin" : "Add origin"}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="rounded border border-line px-3 py-1.5 text-sm hover:bg-surface"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function OriginRow({
  row,
  states,
  isLastActive,
}: {
  row: SenderLocationRow;
  states: StateOption[];
  isLastActive: boolean;
}) {
  const router = useRouter();
  const [expanded, setExpanded] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function remove() {
    setMessage(null);
    const result = await deleteSenderLocationAction({ id: row.id });
    if (result.message) {
      setMessage(result.message);
      setConfirming(false);
    } else {
      startTransition(() => router.refresh());
    }
  }

  return (
    <li className="rounded-[var(--radius-card)] border border-line bg-card p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium">
            {row.name}
            {row.customer_pickup && (
              <span className="ml-2 rounded bg-accent/10 px-1.5 py-0.5 text-xs text-accent">
                customer pickup
              </span>
            )}
            {!row.is_active && (
              <span className="ml-2 rounded bg-surface px-1.5 py-0.5 text-xs text-muted">
                inactive
              </span>
            )}
          </p>
          <p className="mt-0.5 text-xs text-muted">
            {row.address} · {row.phone}
            {(row.state || row.lga) && (
              <> · {[row.lga, row.state].filter(Boolean).join(", ")}</>
            )}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="rounded border border-line px-2 py-1 text-xs hover:bg-surface"
          >
            {expanded ? "Close" : "Edit"}
          </button>
          {confirming ? (
            <span className="flex items-center gap-2 text-xs">
              <span className="text-warn">Delete {row.name}?</span>
              <button type="button" onClick={remove} className="font-medium text-warn">
                Delete
              </button>
              <button type="button" onClick={() => setConfirming(false)}>
                Keep
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className="rounded border border-line px-2 py-1 text-xs text-muted hover:bg-surface"
            >
              Delete
            </button>
          )}
        </div>
      </div>
      {message && <p className="mt-2 text-xs text-warn">{message}</p>}
      {/* Hidden, not unmounted: a stray collapse must not destroy unsaved edits. */}
      <div className={expanded ? "" : "hidden"}>
        <OriginForm
          row={row}
          states={states}
          isLastActive={isLastActive}
          onDone={() => setExpanded(false)}
        />
      </div>
    </li>
  );
}

export function SenderLocations({
  rows,
  states,
}: {
  rows: SenderLocationRow[];
  states: StateOption[];
}) {
  const [adding, setAdding] = useState(false);
  const activeCount = rows.filter((r) => r.is_active).length;

  return (
    <section className="rounded-[var(--radius-card)] border border-line bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Pickup origins</h2>
          <p className="mt-1 text-xs text-muted">
            Where GIG riders collect parcels. Each order ships from the nearest active
            location to the customer, and its shop is who GIG calls to arrange the pickup.
          </p>
        </div>
        {!adding && (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="shrink-0 rounded border border-line px-3 py-1.5 text-sm hover:bg-surface"
          >
            Add origin
          </button>
        )}
      </div>
      {adding && (
        <OriginForm
          row={null}
          states={states}
          isLastActive={false}
          onDone={() => setAdding(false)}
        />
      )}
      <ul className="mt-3 space-y-2">
        {rows.map((row) => (
          <OriginRow
            key={row.id}
            row={row}
            states={states}
            isLastActive={row.is_active && activeCount === 1}
          />
        ))}
      </ul>
      {rows.length === 0 && (
        <p className="mt-3 text-sm text-muted">
          No origins yet — quotes use the built-in Ogudu Mall sender until one is added.
        </p>
      )}
    </section>
  );
}
