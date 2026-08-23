"use client";

import { useState, useTransition } from "react";
import type { WriteState } from "@/app/(shell)/orders/[number]/actions";

/**
 * The AAJ Express fulfilment panel (Plan-43) — rendered only when the order has an
 * AajShipment. GigPanel's sibling, with the differences AAJ's API forces:
 *
 * - TWO steps behind one button: create-booking (free) then process-booking (THE
 *   MONEY — charges our AAJ account). The confirm step says so, and names the
 *   retail figure the customer paid beside the account rate we will be charged.
 * - `booked` is a real resting state: the kill-switch (`process_enabled` false)
 *   stops there on purpose, and so does a refused charge. "Create" from there
 *   re-runs only the charge.
 * - `create_unconfirmed` has a CHECK button (reads AAJ, never charges) instead of
 *   the forbid-retry wall alone — AAJ's records can settle what the answer couldn't.
 * - VOID exists (AAJ reverses until the first hub scan) and a voided shipment can
 *   be captured again.
 * - No wallet line: AAJ exposes no balance endpoint; credit-facility accounts are
 *   post-paid.
 *
 * Scope-wise the buttons only grey (capture and void need `orders.manage`, label
 * and check `orders.operate`); the endpoints re-check on every request.
 */

export interface AajShipmentData {
  status: string;
  booking_id: string;
  tracking_id: string;
  quote_total: string | null;
  cost: string | null;
  charged: string;
  eta_days: number | null;
  label_url: string;
  last_scan: Record<string, unknown>;
  last_status: number | null;
  last_tracked_at: string | null;
  origin?: { id?: number; name?: string; address?: string; state_name?: string };
}

export interface AajPanelData {
  shipment: AajShipmentData;
  can_capture: boolean;
  capture_blocked_reason: string;
  can_check: boolean;
  can_void: boolean;
  void_blocked_reason: string;
  process_enabled: boolean;
}

const STATUS_COPY: Record<string, string> = {
  quoted: "Quoted — no booking yet",
  booked: "Booked with AAJ — NOT yet charged",
  created: "Shipment created — label issued, awaiting AAJ pickup",
  in_transit: "In transit",
  delivered: "Delivered",
  returned: "RETURNED to sender — decide with the customer",
  voided: "Voided — charge reversed; can be rebooked",
  create_unconfirmed: "UNCONFIRMED — check with AAJ before anything else",
  abandoned: "Abandoned (order died before capture)",
};

/** AAJ's scan as one line: the event's description, its location and when. */
function scanLine(scan: Record<string, unknown>): string {
  const meta = (scan.meta ?? {}) as Record<string, unknown>;
  const parts = [scan.description, meta.location, scan.scanType]
    .filter((v): v is string => typeof v === "string" && v.trim() !== "");
  const when = typeof scan.dateTime === "string" ? scan.dateTime.slice(0, 16).replace("T", " ") : "";
  return [parts[0] ?? parts[2] ?? "", parts[1] ? `at ${parts[1]}` : "", when].filter(Boolean).join(" · ");
}

export function AajPanel({
  number,
  data,
  scopes,
  actions,
}: {
  number: string;
  data: AajPanelData;
  scopes: string[];
  actions: {
    capture: (input: { number: string }) => Promise<WriteState>;
    check: (input: { number: string }) => Promise<WriteState>;
    void: (input: { number: string }) => Promise<WriteState>;
    label: (input: { number: string }) => Promise<WriteState>;
  };
}) {
  const { shipment } = data;
  const [state, setState] = useState<WriteState>({});
  const [confirming, setConfirming] = useState<"capture" | "void" | null>(null);
  const [pending, startTransition] = useTransition();

  const mayManage = scopes.includes("orders.manage");
  const mayOperate = scopes.includes("orders.operate");
  const unconfirmed = shipment.status === "create_unconfirmed" || state.code === "capture_unconfirmed";
  const willCost = shipment.cost ?? shipment.quote_total ?? shipment.charged;
  const capturable = ["quoted", "booked", "voided"].includes(shipment.status);

  const run = (action: () => Promise<WriteState>) =>
    startTransition(async () => {
      setState(await action());
      setConfirming(null);
    });

  return (
    <section className="rounded-[var(--radius-card)] border border-line p-4 text-sm">
      <h2 className="text-sm font-medium">AAJ Express delivery</h2>

      <dl className="mt-3 space-y-1">
        <div className="flex justify-between gap-4">
          <dt className="text-muted">Status</dt>
          <dd className={unconfirmed || shipment.status === "returned" ? "font-medium text-warn" : ""}>
            {STATUS_COPY[shipment.status] ?? shipment.status}
          </dd>
        </div>
        {shipment.tracking_id && (
          <div className="flex justify-between gap-4">
            <dt className="text-muted">Tracking id</dt>
            <dd className="font-mono">{shipment.tracking_id}</dd>
          </div>
        )}
        {shipment.booking_id && (
          <div className="flex justify-between gap-4">
            <dt className="text-muted">AAJ booking</dt>
            <dd className="font-mono text-xs">{shipment.booking_id}</dd>
          </div>
        )}
        {shipment.origin?.name && (
          <div className="flex justify-between gap-4">
            <dt className="text-muted">Collecting from</dt>
            {/* Which SHOP must pack this order. AAJ priced the zone from this
                origin's STATE, so the parcel must leave from here. */}
            <dd className="text-right">
              {shipment.origin.name}
              {shipment.origin.address && (
                <span className="block text-xs text-muted">{shipment.origin.address}</span>
              )}
            </dd>
          </div>
        )}
        {shipment.eta_days !== null && shipment.eta_days !== undefined && (
          <div className="flex justify-between gap-4">
            <dt className="text-muted">AAJ&rsquo;s ETA at quote</dt>
            <dd>{shipment.eta_days} {shipment.eta_days === 1 ? "day" : "days"}</dd>
          </div>
        )}
        <div className="flex justify-between gap-4">
          <dt className="text-muted">Customer paid</dt>
          <dd className="tabular-nums">₦{shipment.charged}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted">{shipment.cost ? "AAJ charges us" : "AAJ retail quote"}</dt>
          {/* Two numbers on purpose: the customer is priced from AAJ's retail quote and
              our account books ~14% lower. The gap is margin — visible here, never hidden. */}
          <dd className="tabular-nums">
            ₦{willCost}
            {shipment.cost && shipment.quote_total && shipment.cost !== shipment.quote_total && (
              <span className="block text-xs text-muted">retail quote was ₦{shipment.quote_total}</span>
            )}
          </dd>
        </div>
      </dl>

      {unconfirmed && (
        <p className="mt-3 rounded border border-warn/40 bg-warn/10 p-2 text-xs text-warn">
          AAJ did not confirm the charge and its records could not settle it yet. Press
          <span className="font-medium"> Check with AAJ</span> (it only reads) — if it still cannot
          settle, look the booking up in AAJ&rsquo;s portal by id
          <span className="font-mono"> {shipment.booking_id}</span> before anything else. Never
          create again blind: that could charge twice.
        </p>
      )}

      {!data.process_enabled && capturable && (
        <p className="mt-3 rounded border border-line bg-surface p-2 text-xs text-muted">
          Charging is switched off (AAJ_PROCESS_ENABLED). Creating will book with AAJ for free
          and stop at &ldquo;Booked&rdquo; — the go-live runbook flips it on after the first
          controlled booking is checked in AAJ&rsquo;s portal.
        </p>
      )}

      {state.error && !unconfirmed && (
        <p className="mt-3 text-xs text-warn" role="alert">
          {state.error}
        </p>
      )}
      {state.success && (
        <p className="mt-3 text-xs text-ok" role="status">
          {state.success}
        </p>
      )}

      <div className="mt-4 space-y-2">
        {capturable && !unconfirmed && (
          confirming === "capture" ? (
            <div className="rounded border border-line p-2">
              <p className="text-xs">
                {shipment.status === "booked" ? (
                  <>This charges the existing AAJ booking <span className="font-medium">₦{willCost}</span> to our account and issues the label.</>
                ) : (
                  <>This books the parcel with AAJ (free) and then charges <span className="font-medium">about ₦{willCost}</span> to our AAJ account — the booking step prices the exact figure — and issues the label.</>
                )}
                {shipment.origin?.name ? (
                  <> The parcel leaves from <span className="font-medium">{shipment.origin.name}</span> — that shop must have this order packed.</>
                ) : null}
                {" "}It can be voided until AAJ&rsquo;s first hub scan.
              </p>
              <div className="mt-2 flex gap-2">
                <button
                  onClick={() => run(() => actions.capture({ number }))}
                  disabled={pending}
                  className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                >
                  {pending ? "Booking…" : shipment.status === "booked" ? "Charge and issue label" : "Create shipment"}
                </button>
                <button
                  onClick={() => setConfirming(null)}
                  disabled={pending}
                  className="rounded border border-line px-3 py-1.5 text-xs"
                >
                  Not yet
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setConfirming("capture")}
              disabled={!mayManage || !data.can_capture || pending}
              title={
                !mayManage
                  ? "Needs orders.manage"
                  : !data.can_capture
                    ? data.capture_blocked_reason
                    : undefined
              }
              className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
            >
              {shipment.status === "booked"
                ? "Charge AAJ booking…"
                : shipment.status === "voided"
                  ? "Rebook with AAJ…"
                  : "Create AAJ shipment…"}
            </button>
          )
        )}
        {!data.can_capture && capturable && data.capture_blocked_reason && (
          <p className="text-xs text-muted">{data.capture_blocked_reason}</p>
        )}

        {data.can_check && (
          <button
            onClick={() => run(() => actions.check({ number }))}
            disabled={!mayOperate || pending}
            title={!mayOperate ? "Needs orders.operate" : "Reads AAJ's records; never charges"}
            className="rounded border border-line px-3 py-1.5 text-xs hover:border-accent disabled:opacity-50"
          >
            {pending ? "Asking AAJ…" : "Check with AAJ"}
          </button>
        )}

        {shipment.tracking_id && (
          <div className="flex flex-wrap items-center gap-2">
            {shipment.label_url ? (
              <a
                href={shipment.label_url}
                target="_blank"
                rel="noreferrer"
                className="rounded border border-line px-3 py-1.5 text-xs hover:border-accent"
              >
                Open label PDF
              </a>
            ) : (
              <button
                onClick={() => run(() => actions.label({ number }))}
                disabled={!mayOperate || pending}
                title={!mayOperate ? "Needs orders.operate" : undefined}
                className="rounded border border-line px-3 py-1.5 text-xs hover:border-accent disabled:opacity-50"
              >
                {pending ? "Asking AAJ…" : "Fetch label"}
              </button>
            )}

            {(shipment.status === "created" || shipment.status === "in_transit") && (
              confirming === "void" ? (
                <span className="inline-flex items-center gap-2 rounded border border-warn/40 p-1.5 text-xs">
                  Void {shipment.tracking_id} and reverse ₦{shipment.cost ?? willCost}?
                  <button
                    onClick={() => run(() => actions.void({ number }))}
                    disabled={pending}
                    className="rounded bg-warn px-2 py-1 text-xs font-medium text-white disabled:opacity-50"
                  >
                    {pending ? "Voiding…" : "Void"}
                  </button>
                  <button onClick={() => setConfirming(null)} disabled={pending} className="rounded border border-line px-2 py-1 text-xs">
                    Keep
                  </button>
                </span>
              ) : (
                <button
                  onClick={() => setConfirming("void")}
                  disabled={!mayManage || !data.can_void || pending}
                  title={
                    !mayManage
                      ? "Needs orders.manage"
                      : !data.can_void
                        ? data.void_blocked_reason
                        : "Allowed until AAJ's first hub scan"
                  }
                  className="rounded border border-line px-3 py-1.5 text-xs text-warn hover:border-warn disabled:opacity-50"
                >
                  Void shipment…
                </button>
              )
            )}
          </div>
        )}
      </div>

      {Object.keys(shipment.last_scan ?? {}).length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <h3 className="text-xs font-medium text-muted">Last tracking scan</h3>
          <p className="mt-1 text-xs">{scanLine(shipment.last_scan)}</p>
          {shipment.last_tracked_at && (
            <p className="mt-1 text-[11px] text-muted">
              checked {shipment.last_tracked_at.slice(0, 16).replace("T", " ")}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
