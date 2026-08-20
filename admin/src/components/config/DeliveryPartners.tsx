"use client";

/**
 * Staff oversight of delivery partners (Plan-39). Two halves, two scopes:
 *
 * - Partner accounts (Owner): the kill-switch, the portal login email, and setting
 *   the password. `has_password=false` is the "don't share the portal link yet"
 *   tell — the seed migration creates the login unusable on purpose.
 * - The rate card (Manager+): every zone row, with the two emergency fixes staff
 *   actually need — correct a price / hide a row — plus delete. Full authorship
 *   stays in the partner portal, which is the point of the feature.
 */
import { useState, useTransition } from "react";
import {
  deletePartnerZoneAction,
  savePartnerAction,
  savePartnerZoneAction,
  setPartnerPasswordAction,
  type PartnerSaveState,
} from "@/app/(shell)/settings/partners/actions";
import type { AdminPartnerZoneRow, DeliveryPartnerRow } from "@/lib/partners";
import { formatNaira } from "@/lib/partners";

function Note({ tone, children }: { tone: "warn" | "ok"; children: React.ReactNode }) {
  const cls =
    tone === "warn"
      ? "border-warn/30 bg-warn/5 text-warn"
      : "border-accent/30 bg-accent/5 text-foreground";
  return (
    <p className={`rounded-[var(--radius-card)] border p-3 text-sm ${cls}`}>{children}</p>
  );
}

function PartnerAccountCard({ partner }: { partner: DeliveryPartnerRow }) {
  const [email, setEmail] = useState(partner.email);
  const [password, setPassword] = useState("");
  const [state, setState] = useState<PartnerSaveState>({});
  const [pending, startTransition] = useTransition();

  function run(action: () => Promise<PartnerSaveState>) {
    startTransition(async () => setState(await action()));
  }

  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">
            {partner.name}
            {!partner.has_password && (
              <span className="ml-2 rounded-full border border-warn/40 bg-warn/10 px-2 py-0.5 text-xs text-warn">
                no password set — portal link not usable yet
              </span>
            )}
          </p>
          <p className="mt-0.5 text-sm text-muted">
            {partner.live_zone_count} of {partner.zone_count} areas live at checkout ·
            portal: <code className="text-xs">/partner</code>
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={partner.is_active}
            disabled={pending}
            onChange={(e) => run(() => savePartnerAction({ id: partner.id, is_active: e.target.checked }))}
          />
          <span>{partner.is_active ? "Active" : "Switched off"}</span>
        </label>
      </div>

      {state.message && <p className="mt-3 text-sm text-danger">{state.message}</p>}

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div>
          <label className="block text-sm font-medium" htmlFor={`email-${partner.id}`}>
            Portal login email
          </label>
          <div className="mt-1 flex gap-2">
            <input
              id={`email-${partner.id}`}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
            />
            <button
              type="button"
              disabled={pending || email.trim() === partner.email}
              onClick={() => run(() => savePartnerAction({ id: partner.id, email }))}
              className="rounded-md border border-line px-3 py-2 text-sm transition-colors hover:border-accent/60 disabled:opacity-50"
            >
              Save
            </button>
          </div>
          {state.fieldErrors?.email && (
            <p className="mt-1 text-sm text-danger">{state.fieldErrors.email}</p>
          )}
        </div>
        <div>
          <label className="block text-sm font-medium" htmlFor={`pw-${partner.id}`}>
            Set a new password
          </label>
          <div className="mt-1 flex gap-2">
            <input
              id={`pw-${partner.id}`}
              type="text"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 12 characters"
              autoComplete="off"
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
            />
            <button
              type="button"
              disabled={pending || !password}
              onClick={() =>
                run(async () => {
                  const out = await setPartnerPasswordAction({ id: partner.id, password });
                  if (out.savedAt) setPassword("");
                  return out;
                })
              }
              className="rounded-md border border-line px-3 py-2 text-sm transition-colors hover:border-accent/60 disabled:opacity-50"
            >
              Set
            </button>
          </div>
          {state.fieldErrors?.password && (
            <p className="mt-1 text-sm text-danger">{state.fieldErrors.password}</p>
          )}
          <p className="mt-1 text-xs text-muted">
            Shown once, here — share it with the partner over a channel you trust.
          </p>
        </div>
      </div>
      {state.savedAt && !pending && (
        <p className="mt-3 text-sm text-accent">Saved.</p>
      )}
    </div>
  );
}

function ZoneRow({ zone }: { zone: AdminPartnerZoneRow }) {
  const [price, setPrice] = useState(zone.price === null ? "" : String(Number(zone.price)));
  const [state, setState] = useState<PartnerSaveState>({});
  const [pending, startTransition] = useTransition();

  const dirty = price.trim() !== (zone.price === null ? "" : String(Number(zone.price)));

  function run(action: () => Promise<PartnerSaveState>) {
    startTransition(async () => setState(await action()));
  }

  return (
    <tr className="border-t border-line text-sm">
      <td className="px-3 py-2 text-muted">{zone.state_name}</td>
      <td className="px-3 py-2">{zone.lga_name}</td>
      <td className="px-3 py-2 font-medium">{zone.lcda_name}</td>
      <td className="max-w-64 truncate px-3 py-2 text-muted" title={zone.areas_covered}>
        {zone.areas_covered}
      </td>
      <td className="px-3 py-2 text-muted">{zone.dispatch_zone}</td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={1}
            step={100}
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            className="w-24 rounded-md border border-line bg-surface px-2 py-1 text-sm outline-none focus:border-accent"
          />
          {dirty && (
            <button
              type="button"
              disabled={pending}
              onClick={() => run(() => savePartnerZoneAction({ id: zone.id, price, is_active: zone.is_active }))}
              className="rounded-md border border-line px-2 py-1 text-xs transition-colors hover:border-accent/60"
            >
              Save
            </button>
          )}
        </div>
        {state.fieldErrors?.price && (
          <p className="mt-1 text-xs text-danger">{state.fieldErrors.price}</p>
        )}
        {state.message && <p className="mt-1 text-xs text-danger">{state.message}</p>}
      </td>
      <td className="px-3 py-2">
        {zone.is_active && zone.price !== null ? (
          <span className="text-accent">live</span>
        ) : (
          <span className="text-warn">{zone.price === null ? "needs a price" : "hidden"}</span>
        )}
      </td>
      <td className="px-3 py-2">
        <div className="flex justify-end gap-2">
          <button
            type="button"
            disabled={pending}
            onClick={() => run(() => savePartnerZoneAction({ id: zone.id, price, is_active: !zone.is_active }))}
            className="rounded-md border border-line px-2 py-1 text-xs transition-colors hover:border-accent/60"
          >
            {zone.is_active ? "Hide" : "Offer"}
          </button>
          <button
            type="button"
            disabled={pending}
            onClick={() => {
              if (window.confirm(`Delete ${zone.lcda_name} (${zone.lga_name})?`)) {
                run(() => deletePartnerZoneAction({ id: zone.id }));
              }
            }}
            className="rounded-md border border-danger/30 px-2 py-1 text-xs text-danger transition-colors hover:bg-danger/5"
          >
            Delete
          </button>
        </div>
      </td>
    </tr>
  );
}

export function DeliveryPartners({
  partners,
  partnersError,
  zones,
  zonesError,
}: {
  partners: DeliveryPartnerRow[];
  partnersError: string | null;
  zones: AdminPartnerZoneRow[];
  zonesError: string | null;
}) {
  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h2 className="text-sm font-semibold tracking-tight">Partner accounts</h2>
        {partnersError ? (
          <Note tone="warn">{partnersError}</Note>
        ) : partners.length === 0 ? (
          <Note tone="ok">No delivery partners yet — one arrives by migration, not a form.</Note>
        ) : (
          partners.map((p) => <PartnerAccountCard key={p.id} partner={p} />)
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold tracking-tight">Rate card</h2>
        <p className="text-sm text-muted">
          The partner maintains this in their portal; edits here are for emergencies —
          fixing a typo&apos;d rate or hiding a row the moment a complaint lands.
        </p>
        {zonesError ? (
          <Note tone="warn">{zonesError}</Note>
        ) : zones.length === 0 ? (
          <Note tone="ok">No rate-card rows yet.</Note>
        ) : (
          <div className="overflow-x-auto rounded-[var(--radius-card)] border border-line">
            <table className="w-full min-w-[940px] text-left">
              <thead className="bg-surface text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">State</th>
                  <th className="px-3 py-2 font-medium">LGA</th>
                  <th className="px-3 py-2 font-medium">LCDA</th>
                  <th className="px-3 py-2 font-medium">Areas covered</th>
                  <th className="px-3 py-2 font-medium">Dispatch zone</th>
                  <th className="px-3 py-2 font-medium">Rate</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {zones.map((z) => (
                  <ZoneRow key={z.id} zone={z} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs text-muted">
          {zones.filter((z) => z.is_active && z.price !== null).length} of {zones.length}{" "}
          rows live at checkout · current rates{" "}
          {(() => {
            const live = zones.filter((z) => z.is_active && z.price !== null);
            if (!live.length) return "—";
            const nums = live.map((z) => Number(z.price));
            return `${formatNaira(String(Math.min(...nums)))} – ${formatNaira(String(Math.max(...nums)))}`;
          })()}
        </p>
      </section>
    </div>
  );
}
