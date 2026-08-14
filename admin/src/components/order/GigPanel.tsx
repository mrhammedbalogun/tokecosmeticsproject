"use client";

import { useState, useTransition } from "react";
import type { WriteState } from "@/app/(shell)/orders/[number]/actions";

/**
 * The GIG fulfilment panel — rendered only when the order has a GigShipment.
 *
 * THE CAPTURE BUTTON IS THE MONEY. Pressing it debits the GIG wallet the full
 * quote and dispatches a rider, irrevocably (no cancel API exists). Hence:
 * a confirm step naming the amount, the button disabled with the backend's own
 * reason when capture is illegal, and the `capture_unconfirmed` answer rendered
 * as a forbid-retry warning rather than an error a person would naturally retry.
 *
 * Scope-wise the buttons only grey (capture needs `orders.manage`, label
 * `orders.operate`); the endpoints re-check on every request — greying is
 * ergonomics, exactly like the sidebar.
 */

export interface GigShipmentData {
  status: string;
  waybill: string;
  cost: string | null;
  charged: string;
  quote: { breakdown?: Record<string, unknown>; price?: string };
  label_url: string;
  capture_api_id: string;
  last_scan: Record<string, unknown>;
  last_tracked_at: string | null;
  /** Centre-pickup snapshot from placement (32b slice 5); {} for door shipments. */
  centre?: { id?: number; name?: string; address?: string };
  /** Sender-origin snapshot from placement (Plan-34); {} = the built-in env sender. */
  origin?: { id?: number; name?: string; address?: string };
}

export interface GigPanelData {
  shipment: GigShipmentData;
  wallet_balance: string | null;
  can_capture: boolean;
  capture_blocked_reason: string;
}

const STATUS_COPY: Record<string, string> = {
  quoted: "Quoted — no waybill yet",
  created: "Waybill created — rider dispatched",
  in_transit: "In transit",
  delivered: "Delivered",
  create_unconfirmed: "UNCONFIRMED — check with GIG before anything else",
  abandoned: "Abandoned (order died before capture)",
};

export function GigPanel({
  number,
  data,
  scopes,
  actions,
}: {
  number: string;
  data: GigPanelData;
  scopes: string[];
  actions: {
    capture: (input: { number: string }) => Promise<WriteState>;
    label: (input: { number: string }) => Promise<WriteState>;
  };
}) {
  const { shipment } = data;
  const [state, setState] = useState<WriteState>({});
  const [confirming, setConfirming] = useState(false);
  const [pending, startTransition] = useTransition();

  const mayCapture = scopes.includes("orders.manage");
  const mayLabel = scopes.includes("orders.operate");
  const quoteTotal = shipment.quote?.price ?? shipment.charged;
  const unconfirmed = shipment.status === "create_unconfirmed" || state.code === "capture_unconfirmed";

  const run = (action: () => Promise<WriteState>) =>
    startTransition(async () => {
      setState(await action());
      setConfirming(false);
    });

  return (
    <section className="rounded-[var(--radius-card)] border border-line p-4 text-sm">
      <h2 className="text-sm font-medium">GIG delivery</h2>

      <dl className="mt-3 space-y-1">
        <div className="flex justify-between gap-4">
          <dt className="text-muted">Status</dt>
          <dd className={unconfirmed ? "font-medium text-warn" : ""}>
            {STATUS_COPY[shipment.status] ?? shipment.status}
          </dd>
        </div>
        {shipment.waybill && (
          <div className="flex justify-between gap-4">
            <dt className="text-muted">Waybill</dt>
            <dd className="font-mono">{shipment.waybill}</dd>
          </div>
        )}
        {shipment.centre?.name && (
          <div className="flex justify-between gap-4">
            <dt className="text-muted">Pickup centre</dt>
            {/* Routing, not preference: capture sends this centre's id to GIG, and
                GIG does NOT validate it — what you see here is where the parcel goes. */}
            <dd className="text-right">
              {shipment.centre.name}
              {shipment.centre.address && (
                <span className="block text-xs text-muted">{shipment.centre.address}</span>
              )}
            </dd>
          </div>
        )}
        {shipment.origin?.name && (
          <div className="flex justify-between gap-4">
            <dt className="text-muted">Collecting from</dt>
            {/* Which SHOP must pack this order (Plan-34): the rider is sent to this
                origin's pin. An Ogudu desk must not capture an Abuja-routed shipment. */}
            <dd className="text-right">
              {shipment.origin.name}
              {shipment.origin.address && (
                <span className="block text-xs text-muted">{shipment.origin.address}</span>
              )}
            </dd>
          </div>
        )}
        <div className="flex justify-between gap-4">
          <dt className="text-muted">Customer paid</dt>
          <dd className="tabular-nums">₦{shipment.charged}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted">{shipment.cost ? "Wallet debited" : "Will cost"}</dt>
          <dd className="tabular-nums">₦{shipment.cost ?? quoteTotal}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted">GIG wallet</dt>
          {/* "unknown" is honest: GIG reports no balance for some accounts, and a
              missing cache is not a zero. */}
          <dd className="tabular-nums">
            {data.wallet_balance === null ? "unknown" : `₦${data.wallet_balance}`}
          </dd>
        </div>
      </dl>

      {unconfirmed && (
        <p className="mt-3 rounded border border-warn/40 bg-warn/10 p-2 text-xs text-warn">
          The capture timed out. GIG may have created a waybill and debited the wallet —
          confirm with GIG (quote apiId{" "}
          <span className="font-mono">{shipment.capture_api_id || "in the timeline"}</span>)
          before doing anything else. Retrying blind can pay twice and dispatch two riders.
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
        {shipment.status === "quoted" && !unconfirmed && (
          confirming ? (
            <div className="rounded border border-line p-2">
              <p className="text-xs">
                This debits <span className="font-medium">₦{quoteTotal}</span> from the GIG
                wallet and dispatches a rider to collect
                {shipment.origin?.name ? (
                  <>
                    {" "}from <span className="font-medium">{shipment.origin.name}</span> —
                    that shop must have this order packed
                  </>
                ) : null}
                . It cannot be cancelled or amended.
                {/* Cutoff confirmed by GIG 2026-08-11 (runbook §2). */}
                {" "}GIG&rsquo;s cutoff is 3&nbsp;pm — waybills created later are picked up
                the next day.
              </p>
              <div className="mt-2 flex gap-2">
                <button
                  onClick={() => run(() => actions.capture({ number }))}
                  disabled={pending}
                  className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                >
                  {pending ? "Creating…" : "Create waybill"}
                </button>
                <button
                  onClick={() => setConfirming(false)}
                  disabled={pending}
                  className="rounded border border-line px-3 py-1.5 text-xs"
                >
                  Not yet
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setConfirming(true)}
              disabled={!mayCapture || !data.can_capture || pending}
              title={
                !mayCapture
                  ? "Needs orders.manage"
                  : !data.can_capture
                    ? data.capture_blocked_reason
                    : undefined
              }
              className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
            >
              Create GIG waybill…
            </button>
          )
        )}
        {!data.can_capture && shipment.status === "quoted" && data.capture_blocked_reason && (
          <p className="text-xs text-muted">{data.capture_blocked_reason}</p>
        )}

        {shipment.waybill && (
          <div className="flex items-center gap-2">
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
                disabled={!mayLabel || pending}
                title={!mayLabel ? "Needs orders.operate" : undefined}
                className="rounded border border-line px-3 py-1.5 text-xs hover:border-accent disabled:opacity-50"
              >
                {pending ? "Asking GIG…" : "Fetch label"}
              </button>
            )}
          </div>
        )}
      </div>

      {Object.keys(shipment.last_scan ?? {}).length > 0 && (
        <div className="mt-4 border-t border-line pt-3">
          <h3 className="text-xs font-medium text-muted">Last tracking scan</h3>
          {/* Verbatim, because GIG's status vocabulary is unpublished — showing the raw
              scan is truthful even when our status map is behind. */}
          <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all text-[11px] text-muted">
            {JSON.stringify(shipment.last_scan, null, 1)}
          </pre>
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
