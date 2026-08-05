"use client";

/**
 * "What would a customer HERE be offered?" — the global address tester on the
 * delivery list. Unlike the per-option mirror on the coverage page, this asks the
 * BACKEND matcher (the code that decides at checkout), so its answer includes the
 * interplay the mirror cannot see: currency filtering, is_active, sort order, every
 * option at once. Carrier options are shown without a live quote — coverage truth,
 * not a GIG call per keystroke.
 */
import { startTransition, useMemo, useState } from "react";
import {
  previewDeliveryAction,
  type DeliveryPreviewOption,
} from "@/app/(shell)/settings/delivery/actions";
import { buildTree, lowerLabel, regionsOf, type RegionRow } from "@/lib/regions";
import type { CountryRef } from "@/lib/reference";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";

export function DeliveryTester({
  countries,
  regions,
}: {
  countries: CountryRef[];
  regions: RegionRow[];
}) {
  const [countryCode, setCountryCode] = useState(
    countries.find((c) => !c.is_rest_of_world)?.code ?? "",
  );
  const [stateId, setStateId] = useState("");
  const [areaId, setAreaId] = useState("");
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<{
    options?: DeliveryPreviewOption[];
    resolvedCountry?: string;
    message?: string;
  } | null>(null);

  const country = countries.find((c) => c.code === countryCode);
  const tree = useMemo(
    () => buildTree(regionsOf(regions, countryCode)),
    [regions, countryCode],
  );
  const areas = tree.find((n) => n.state.id === Number(stateId))?.areas ?? [];
  const stateLabel = country?.state_label ?? "State";
  const areaLabel = country?.area_label ?? "Area";

  const run = (next: { country?: string; state?: string; area?: string }) => {
    const c = next.country ?? countryCode;
    const s = next.state ?? stateId;
    const a = next.area ?? areaId;
    setPending(true);
    startTransition(async () => {
      const res = await previewDeliveryAction({
        country: c,
        state_region: s ? Number(s) : undefined,
        area_region: a ? Number(a) : undefined,
      });
      setPending(false);
      setResult(res);
    });
  };

  return (
    <section className="rounded-[var(--radius-card)] border border-line p-4">
      <h2 className="text-sm font-semibold">Test an address</h2>
      <p className="mt-1 text-sm text-muted">
        The backend matcher answers — exactly what a customer at this address would be
        offered at checkout, in order.
      </p>

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <label className="block text-xs text-muted">
          Country
          <select
            value={countryCode}
            onChange={(e) => {
              setCountryCode(e.target.value);
              setStateId("");
              setAreaId("");
              run({ country: e.target.value, state: "", area: "" });
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
              run({ state: e.target.value, area: "" });
            }}
            disabled={!tree.length}
            className={`mt-1 ${FIELD}`}
          >
            <option value="">
              {tree.length ? `Anywhere in the country` : "No regions"}
            </option>
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
            onChange={(e) => {
              setAreaId(e.target.value);
              run({ area: e.target.value });
            }}
            disabled={!areas.length}
            className={`mt-1 ${FIELD}`}
          >
            <option value="">
              {areas.length ? `Anywhere in the ${lowerLabel(stateLabel)}` : "—"}
            </option>
            {areas.map((area) => (
              <option key={area.id} value={area.id}>
                {area.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {pending && <p className="mt-3 text-sm text-muted">Checking…</p>}
      {!pending && result?.message && (
        <p className="mt-3 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn" role="alert">
          {result.message}
        </p>
      )}
      {!pending && result?.options && (
        <div className="mt-3">
          {result.resolvedCountry && result.resolvedCountry !== countryCode && (
            <p className="mb-2 text-xs text-muted">
              Resolves to the {result.resolvedCountry} market at checkout.
            </p>
          )}
          {result.options.length === 0 ? (
            <p className="rounded border border-warn/40 bg-warn/5 p-2 text-sm text-warn" role="status">
              No options — a customer here could not complete checkout.
            </p>
          ) : (
            <ul className="divide-y divide-line rounded border border-line">
              {result.options.map((o) => (
                <li key={o.id} className="flex items-center justify-between px-3 py-2 text-sm">
                  <span>
                    {o.name}
                    <span className="ml-2 text-xs text-muted">
                      {o.min_days}–{o.max_days} days
                    </span>
                  </span>
                  <span className="text-xs">
                    {o.kind === "carrier" ? (
                      <span className="text-muted">quoted live by carrier</span>
                    ) : o.quote_required ? (
                      <span className="text-muted">{o.disclaimer || "quoted after order"}</span>
                    ) : (
                      <span>
                        {o.price} {o.currency}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
