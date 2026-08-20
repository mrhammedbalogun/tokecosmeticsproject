"use client";

/**
 * Plan-41 delivery controls, two halves on one page:
 *
 * - Blocked areas: subtractive rules — pick a service, then how far to narrow.
 *   Country alone blocks the whole country; adding a state narrows to the state;
 *   adding an LGA narrows to that LGA. Pause keeps a rule without enforcing it.
 * - Fee masking: one percentage per service, added on top of its real fee at
 *   checkout — ₦5,000 masked at 10% shows and charges ₦5,500.
 */
import { useMemo, useState, useTransition } from "react";
import {
  createBlockAction,
  createMaskAction,
  deleteBlockAction,
  deleteMaskAction,
  saveBlockAction,
  saveMaskAction,
  type ControlSaveState,
} from "@/app/(shell)/settings/delivery-controls/actions";
import type {
  DeliveryBlockRow,
  DeliveryFeeMaskRow,
  DeliveryServiceRef,
} from "@/lib/delivery-controls";
import { buildTree, lowerLabel, regionsOf, type RegionRow } from "@/lib/regions";
import type { CountryRef } from "@/lib/reference";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";
const BUTTON =
  "rounded-md border border-line px-3 py-2 text-sm transition-colors hover:border-accent/60 disabled:opacity-50";
const SMALL_BUTTON =
  "rounded-md border border-line px-2 py-1 text-xs transition-colors hover:border-accent/60 disabled:opacity-50";

const KIND_LABEL: Record<DeliveryServiceRef["kind"], string> = {
  carrier: "courier",
  partner: "delivery partner",
  store: "store pickup",
  manual: "delivery option",
};

function whereText(block: DeliveryBlockRow, countries: CountryRef[]): string {
  const country =
    countries.find((c) => c.code === block.country_code)?.name ?? block.country_code;
  if (block.area_name) return `${country} → ${block.state_name} → ${block.area_name}`;
  if (block.state_name) return `${country} → ${block.state_name} (whole state)`;
  return `${country} (whole country)`;
}

function BlockRow({
  block,
  countries,
}: {
  block: DeliveryBlockRow;
  countries: CountryRef[];
}) {
  const [state, setState] = useState<ControlSaveState>({});
  const [pending, startTransition] = useTransition();

  function run(action: () => Promise<ControlSaveState>) {
    startTransition(async () => setState(await action()));
  }

  return (
    <tr className="border-t border-line text-sm">
      <td className="px-3 py-2 font-medium">{block.service_name}</td>
      <td className="px-3 py-2">{whereText(block, countries)}</td>
      <td className="px-3 py-2">
        {block.is_active ? (
          <span className="text-danger">blocking</span>
        ) : (
          <span className="text-muted">paused</span>
        )}
        {state.message && <p className="mt-1 text-xs text-danger">{state.message}</p>}
      </td>
      <td className="px-3 py-2">
        <div className="flex justify-end gap-2">
          <button
            type="button"
            disabled={pending}
            onClick={() =>
              run(() => saveBlockAction({ id: block.id, is_active: !block.is_active }))
            }
            className={SMALL_BUTTON}
          >
            {block.is_active ? "Pause" : "Resume"}
          </button>
          <button
            type="button"
            disabled={pending}
            onClick={() => {
              if (window.confirm(`Remove this block on ${block.service_name}?`)) {
                run(() => deleteBlockAction({ id: block.id }));
              }
            }}
            className="rounded-md border border-danger/30 px-2 py-1 text-xs text-danger transition-colors hover:bg-danger/5 disabled:opacity-50"
          >
            Delete
          </button>
        </div>
      </td>
    </tr>
  );
}

function NewBlockForm({
  services,
  countries,
  regions,
}: {
  services: DeliveryServiceRef[];
  countries: CountryRef[];
  regions: RegionRow[];
}) {
  const [serviceCode, setServiceCode] = useState("");
  const [countryCode, setCountryCode] = useState(
    countries.find((c) => c.is_default)?.code ??
      countries.find((c) => !c.is_rest_of_world)?.code ??
      "",
  );
  const [stateId, setStateId] = useState("");
  const [areaId, setAreaId] = useState("");
  const [state, setState] = useState<ControlSaveState>({});
  const [pending, startTransition] = useTransition();

  const country = countries.find((c) => c.code === countryCode);
  const tree = useMemo(
    () => buildTree(regionsOf(regions, countryCode)),
    [regions, countryCode],
  );
  const areas = tree.find((n) => n.state.id === Number(stateId))?.areas ?? [];
  const stateLabel = country?.state_label ?? "State";
  const areaLabel = country?.area_label ?? "Area";

  const scopeSentence = !serviceCode
    ? null
    : areaId
      ? `Blocked in ONE ${lowerLabel(areaLabel)} only.`
      : stateId
        ? `Blocked across the whole ${lowerLabel(stateLabel)}.`
        : `Blocked across the whole country.`;

  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-surface p-4">
      <p className="text-sm font-medium">Add a block</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-4">
        <label className="block text-xs text-muted">
          Delivery service
          <select
            value={serviceCode}
            onChange={(e) => setServiceCode(e.target.value)}
            className={`mt-1 ${FIELD}`}
          >
            <option value="">Choose a service…</option>
            {services.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name} ({KIND_LABEL[s.kind]})
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-muted">
          Country
          <select
            value={countryCode}
            onChange={(e) => {
              setCountryCode(e.target.value);
              setStateId("");
              setAreaId("");
            }}
            className={`mt-1 ${FIELD}`}
          >
            {countries.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-muted">
          {stateLabel}
          <select
            value={stateId}
            onChange={(e) => {
              setStateId(e.target.value);
              setAreaId("");
            }}
            disabled={!tree.length}
            className={`mt-1 ${FIELD}`}
          >
            <option value="">{tree.length ? "Whole country" : "No regions"}</option>
            {tree.map((node) => (
              <option key={node.state.id} value={node.state.id}>
                {node.state.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-muted">
          {areaLabel}
          <select
            value={areaId}
            onChange={(e) => setAreaId(e.target.value)}
            disabled={!areas.length}
            className={`mt-1 ${FIELD}`}
          >
            <option value="">
              {areas.length ? `Whole ${lowerLabel(stateLabel)}` : "—"}
            </option>
            {areas.map((area) => (
              <option key={area.id} value={area.id}>
                {area.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={pending || !serviceCode}
          onClick={() =>
            startTransition(async () => {
              const out = await createBlockAction({
                service_code: serviceCode,
                country_code: countryCode,
                state_region: stateId ? Number(stateId) : null,
                area_region: areaId ? Number(areaId) : null,
              });
              setState(out);
              if (out.savedAt) {
                setStateId("");
                setAreaId("");
              }
            })
          }
          className={BUTTON}
        >
          Block it
        </button>
        {scopeSentence && <p className="text-xs text-muted">{scopeSentence}</p>}
      </div>
      {state.message && <p className="mt-2 text-sm text-danger">{state.message}</p>}
      {Object.entries(state.fieldErrors ?? {}).map(([field, error]) => (
        <p key={field} className="mt-1 text-sm text-danger">
          {error}
        </p>
      ))}
      {state.savedAt && !pending && <p className="mt-2 text-sm text-accent">Blocked.</p>}
    </div>
  );
}

function MaskRow({ mask }: { mask: DeliveryFeeMaskRow }) {
  const [percent, setPercent] = useState(String(Number(mask.percent)));
  const [state, setState] = useState<ControlSaveState>({});
  const [pending, startTransition] = useTransition();

  const dirty = percent.trim() !== String(Number(mask.percent));

  function run(action: () => Promise<ControlSaveState>) {
    startTransition(async () => setState(await action()));
  }

  return (
    <tr className="border-t border-line text-sm">
      <td className="px-3 py-2 font-medium">{mask.service_name}</td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={0}
            max={400}
            step={0.5}
            value={percent}
            onChange={(e) => setPercent(e.target.value)}
            className="w-20 rounded-md border border-line bg-surface px-2 py-1 text-sm outline-none focus:border-accent"
          />
          <span className="text-xs text-muted">%</span>
          {dirty && (
            <button
              type="button"
              disabled={pending}
              onClick={() => run(() => saveMaskAction({ id: mask.id, percent }))}
              className={SMALL_BUTTON}
            >
              Save
            </button>
          )}
        </div>
        {state.fieldErrors?.percent && (
          <p className="mt-1 text-xs text-danger">{state.fieldErrors.percent}</p>
        )}
        {state.message && <p className="mt-1 text-xs text-danger">{state.message}</p>}
      </td>
      <td className="px-3 py-2">
        {mask.is_active ? (
          <span className="text-accent">on</span>
        ) : (
          <span className="text-muted">off</span>
        )}
      </td>
      <td className="px-3 py-2">
        <div className="flex justify-end gap-2">
          <button
            type="button"
            disabled={pending}
            onClick={() => run(() => saveMaskAction({ id: mask.id, is_active: !mask.is_active }))}
            className={SMALL_BUTTON}
          >
            {mask.is_active ? "Turn off" : "Turn on"}
          </button>
          <button
            type="button"
            disabled={pending}
            onClick={() => {
              if (window.confirm(`Remove the mask on ${mask.service_name}?`)) {
                run(() => deleteMaskAction({ id: mask.id }));
              }
            }}
            className="rounded-md border border-danger/30 px-2 py-1 text-xs text-danger transition-colors hover:bg-danger/5 disabled:opacity-50"
          >
            Delete
          </button>
        </div>
      </td>
    </tr>
  );
}

function NewMaskForm({
  services,
  masks,
}: {
  services: DeliveryServiceRef[];
  masks: DeliveryFeeMaskRow[];
}) {
  const taken = new Set(masks.map((m) => m.service_code));
  const available = services.filter((s) => !taken.has(s.code));
  const [serviceCode, setServiceCode] = useState("");
  const [percent, setPercent] = useState("");
  const [state, setState] = useState<ControlSaveState>({});
  const [pending, startTransition] = useTransition();

  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-surface p-4">
      <p className="text-sm font-medium">Add a mask</p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="block text-xs text-muted">
          Delivery service
          <select
            value={serviceCode}
            onChange={(e) => setServiceCode(e.target.value)}
            className={`mt-1 ${FIELD} min-w-56`}
          >
            <option value="">Choose a service…</option>
            {available.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name} ({KIND_LABEL[s.kind]})
              </option>
            ))}
          </select>
        </label>
        <label className="block text-xs text-muted">
          Percent added
          <div className="mt-1 flex items-center gap-2">
            <input
              type="number"
              min={0}
              max={400}
              step={0.5}
              value={percent}
              onChange={(e) => setPercent(e.target.value)}
              placeholder="10"
              className="w-24 rounded-md border border-line bg-surface px-2 py-1.5 text-sm outline-none focus:border-accent"
            />
            <span className="text-sm text-muted">%</span>
          </div>
        </label>
        <button
          type="button"
          disabled={pending || !serviceCode || !percent.trim()}
          onClick={() =>
            startTransition(async () => {
              const out = await createMaskAction({ service_code: serviceCode, percent });
              setState(out);
              if (out.savedAt) {
                setServiceCode("");
                setPercent("");
              }
            })
          }
          className={BUTTON}
        >
          Add mask
        </button>
      </div>
      {state.message && <p className="mt-2 text-sm text-danger">{state.message}</p>}
      {Object.entries(state.fieldErrors ?? {}).map(([field, error]) => (
        <p key={field} className="mt-1 text-sm text-danger">
          {error}
        </p>
      ))}
      {state.savedAt && !pending && <p className="mt-2 text-sm text-accent">Added.</p>}
    </div>
  );
}

export function DeliveryControls({
  services,
  blocks,
  masks,
  countries,
  regions,
}: {
  services: DeliveryServiceRef[];
  blocks: DeliveryBlockRow[];
  masks: DeliveryFeeMaskRow[];
  countries: CountryRef[];
  regions: RegionRow[];
}) {
  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h2 className="text-sm font-semibold tracking-tight">Blocked areas</h2>
        <p className="text-sm text-muted">
          A blocked service disappears from checkout at matching addresses the moment
          the rule is saved. Everywhere else it stays exactly as it was.
        </p>
        {blocks.length === 0 ? (
          <p className="rounded-[var(--radius-card)] border border-line p-3 text-sm text-muted">
            No blocks yet — every service shows everywhere it covers.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line">
            <table className="w-full min-w-[640px] text-left">
              <thead className="bg-surface text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Service</th>
                  <th className="px-3 py-2 font-medium">Where</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {blocks.map((b) => (
                  <BlockRow key={b.id} block={b} countries={countries} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {countries.length > 0 ? (
          <NewBlockForm services={services} countries={countries} regions={regions} />
        ) : (
          <p className="text-sm text-muted">
            The country list could not be loaded — reload to add a block.
          </p>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold tracking-tight">Fee masking</h2>
        <p className="text-sm text-muted">
          Adds a percentage on top of the service&apos;s real fee, everywhere it is
          offered — a ₦5,000 delivery masked at 10% shows and charges ₦5,500. The
          service still bills the real fee; the difference is margin, and free
          delivery stays free.
        </p>
        {masks.length === 0 ? (
          <p className="rounded-[var(--radius-card)] border border-line p-3 text-sm text-muted">
            No masks yet — every service charges its real fee.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line">
            <table className="w-full min-w-[560px] text-left">
              <thead className="bg-surface text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Service</th>
                  <th className="px-3 py-2 font-medium">Percent added</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {masks.map((m) => (
                  <MaskRow key={m.id} mask={m} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        <NewMaskForm services={services} masks={masks} />
      </section>
    </div>
  );
}
