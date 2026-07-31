"use client";

/**
 * The operational controls: move the order, record tracking, refund, annotate, clear a flag.
 *
 * ── ONLY LEGAL MOVES ARE OFFERED, AND UNAUTHORISED ONES ARE GREYED RATHER THAN HIDDEN ─
 *
 * `allowed_transitions` comes from the API with the scope each move needs. A hidden button
 * is indistinguishable from a missing feature — Support asking "why can't I cancel?" is a
 * better outcome than Support concluding the admin is broken.
 *
 * ── THE TWO REFUNDS ARE SEPARATE CONTROLS ───────────────────────────────────────────
 *
 * A gateway refund MOVES money. A manual refund RECORDS money the operator already sent
 * from the bank. Collapsing them into one "Refund" button is how somebody comes to believe
 * money moved when it did not — so they are two panels with two verbs, and the manual one
 * says outright that it moves nothing.
 */
import { useState, useTransition } from "react";
import type { WriteState } from "@/app/(shell)/orders/[number]/actions";
import { mayTransition, type OrderDetail, type OrderPayment } from "@/lib/order-detail";
import { reviewReasons, statusLabel } from "@/lib/orders";

const FIELD =
  "w-full rounded border border-line bg-surface px-2 py-1.5 text-sm focus:border-accent focus:outline-none";
const GHOST = "rounded border border-line px-3 py-1.5 text-sm hover:border-accent disabled:opacity-40";

export interface OpsActions {
  transition: (i: { number: string; toStatus: string; message: string }) => Promise<WriteState>;
  tracking: (i: { number: string; carrier: string; trackingNumber: string }) => Promise<WriteState>;
  note: (i: { number: string; note: string }) => Promise<WriteState>;
  resolveReview: (i: { number: string }) => Promise<WriteState>;
  gatewayRefund: (i: {
    number: string; amount: string; reason: string; restock: boolean; paymentId: number;
  }) => Promise<WriteState>;
  manualRefund: (i: {
    number: string; amount: string; bankReference: string; note: string; restock: boolean;
  }) => Promise<WriteState>;
}

function Result({ state }: { state: WriteState }) {
  if (state.error) {
    return (
      <p className="mt-2 rounded border border-warn/30 bg-warn/5 p-2 text-sm text-warn">
        {state.error}
      </p>
    );
  }
  if (state.success) {
    return (
      <p className="mt-2 rounded border border-ok/30 bg-ok/10 p-2 text-sm text-ok" role="status">
        {state.success}
      </p>
    );
  }
  return null;
}

export function OrderOpsPanel({
  order,
  scopes,
  actions,
}: {
  order: OrderDetail;
  scopes: readonly string[];
  actions: OpsActions;
}) {
  const [pending, start] = useTransition();
  const [move, setMove] = useState<WriteState>({});
  const [track, setTrack] = useState<WriteState>({});
  const [noteState, setNoteState] = useState<WriteState>({});
  const [refund, setRefund] = useState<WriteState>({});
  const [flag, setFlag] = useState<WriteState>({});

  const [message, setMessage] = useState("");
  const [carrier, setCarrier] = useState(order.tracking_carrier);
  const [trackingNumber, setTrackingNumber] = useState(order.tracking_number);
  const [adminNote, setAdminNote] = useState(order.admin_note);

  // Refunds are taken against the goods payment; a freight receipt is a different thing.
  const refundable: OrderPayment | undefined = order.payments.find(
    (p) => p.purpose === "goods" && Number(p.refundable) > 0,
  );
  const [refundAmount, setRefundAmount] = useState(refundable?.refundable ?? "");
  const [refundReason, setRefundReason] = useState("");
  const [refundReference, setRefundReference] = useState("");
  // Defaulted ON: the goods usually come back, and an operator who forgets is more likely
  // to want stock returned than not.
  const [restock, setRestock] = useState(true);

  const flags = reviewReasons(order);

  return (
    <div className="space-y-4">
      {flags.length > 0 && (
        <section className="rounded-[var(--radius-card)] border border-warn/40 bg-warn/5 p-4">
          <h2 className="text-sm font-medium text-warn">Needs attention</h2>
          <ul className="mt-2 space-y-1 text-sm text-warn">
            {flags.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => start(async () => setFlag(await actions.resolveReview({ number: order.number })))}
            disabled={pending}
            className={`mt-3 ${GHOST}`}
          >
            Clear the flag
          </button>
          <p className="mt-1 text-xs text-muted">
            {/* The endpoint's own docstring makes this point; it belongs on screen too. */}
            Clearing moves no money. It takes the note down — it does not fix the problem.
          </p>
          <Result state={flag} />
        </section>
      )}

      <section className="rounded-[var(--radius-card)] border border-line p-4">
        <h2 className="text-sm font-medium">Move this order</h2>
        {order.allowed_transitions.length === 0 ? (
          <p className="mt-2 text-sm text-muted">
            {statusLabel(order.status)} is the end of the road — there is nowhere to move it.
          </p>
        ) : (
          <>
            <input
              type="text"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Note for the timeline (optional)"
              aria-label="Transition message"
              className={`mt-2 ${FIELD}`}
            />
            <div className="mt-2 flex flex-wrap gap-2">
              {order.allowed_transitions.map((t) => {
                const allowed = mayTransition(t, scopes);
                return (
                  <button
                    key={t.status}
                    type="button"
                    disabled={pending || !allowed}
                    title={
                      allowed
                        ? undefined
                        : `Needs the ${t.requires_scope} scope, which your role does not have.`
                    }
                    onClick={() =>
                      start(async () =>
                        setMove(
                          await actions.transition({
                            number: order.number,
                            toStatus: t.status,
                            message,
                          }),
                        ),
                      )
                    }
                    className={GHOST}
                  >
                    {statusLabel(t.status)}
                  </button>
                );
              })}
            </div>
          </>
        )}
        <Result state={move} />
      </section>

      <section className="rounded-[var(--radius-card)] border border-line p-4">
        <h2 className="text-sm font-medium">Tracking</h2>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <input
            type="text" value={carrier} onChange={(e) => setCarrier(e.target.value)}
            placeholder="Carrier" aria-label="Carrier" className={FIELD}
          />
          <input
            type="text" value={trackingNumber} onChange={(e) => setTrackingNumber(e.target.value)}
            placeholder="Tracking number" aria-label="Tracking number"
            className={`${FIELD} font-mono`}
          />
        </div>
        <button
          type="button"
          disabled={pending}
          onClick={() =>
            start(async () =>
              setTrack(await actions.tracking({ number: order.number, carrier, trackingNumber })),
            )
          }
          className={`mt-2 ${GHOST}`}
        >
          Save tracking
        </button>
        <p className="mt-1 text-xs text-muted">
          {/* AdminOrderTrackingView's docstring: saving tracking sends nothing. Moving to
              shipped is what emails the customer. Set tracking first, then ship. */}
          Saving sends nothing. The customer is emailed when you mark it shipped.
        </p>
        <Result state={track} />
      </section>

      {refundable && (
        <section className="rounded-[var(--radius-card)] border border-line p-4">
          <h2 className="text-sm font-medium">Refund</h2>
          <p className="mt-1 text-xs text-muted">
            {refundable.refundable} {order.currency} left against the{" "}
            {refundable.gateway.replace(/_/g, " ")} payment.
          </p>

          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <input
              type="text" inputMode="decimal" value={refundAmount}
              onChange={(e) => setRefundAmount(e.target.value)}
              aria-label="Refund amount" className={`${FIELD} tabular-nums`}
            />
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox" checked={restock} onChange={(e) => setRestock(e.target.checked)}
                className="h-4 w-4 rounded border-line"
              />
              Put the stock back
            </label>
          </div>

          {refundable.gateway === "bank_transfer" ? (
            <div className="mt-3 rounded border border-line p-3">
              <h3 className="text-xs font-medium">Record a transfer you already sent</h3>
              <p className="mt-1 text-xs text-muted">
                {/* The distinction that keeps somebody from thinking money moved. */}
                This records money you sent from the bank. It does not send any.
              </p>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <input
                  type="text" value={refundReference}
                  onChange={(e) => setRefundReference(e.target.value)}
                  placeholder="Bank reference" aria-label="Refund bank reference"
                  className={`${FIELD} font-mono`}
                />
                <input
                  type="text" value={refundReason} onChange={(e) => setRefundReason(e.target.value)}
                  placeholder="Note" aria-label="Refund note" className={FIELD}
                />
              </div>
              <button
                type="button" disabled={pending}
                onClick={() =>
                  start(async () =>
                    setRefund(
                      await actions.manualRefund({
                        number: order.number, amount: refundAmount,
                        bankReference: refundReference, note: refundReason, restock,
                      }),
                    ),
                  )
                }
                className={`mt-2 ${GHOST}`}
              >
                Record refund
              </button>
            </div>
          ) : (
            <div className="mt-3 rounded border border-line p-3">
              <h3 className="text-xs font-medium">Send a refund through the gateway</h3>
              <input
                type="text" value={refundReason} onChange={(e) => setRefundReason(e.target.value)}
                placeholder="Reason" aria-label="Refund reason" className={`mt-2 ${FIELD}`}
              />
              <button
                type="button" disabled={pending}
                onClick={() =>
                  start(async () =>
                    setRefund(
                      await actions.gatewayRefund({
                        number: order.number, amount: refundAmount, reason: refundReason,
                        restock, paymentId: refundable.id,
                      }),
                    ),
                  )
                }
                className="mt-2 rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40"
              >
                Send refund
              </button>
            </div>
          )}
          <Result state={refund} />
        </section>
      )}

      <section className="rounded-[var(--radius-card)] border border-line p-4">
        <h2 className="text-sm font-medium">Internal note</h2>
        <textarea
          value={adminNote} onChange={(e) => setAdminNote(e.target.value)} rows={3}
          placeholder="Only staff see this." aria-label="Internal note"
          className={`mt-2 ${FIELD}`}
        />
        <button
          type="button" disabled={pending}
          onClick={() =>
            start(async () => setNoteState(await actions.note({ number: order.number, note: adminNote })))
          }
          className={`mt-2 ${GHOST}`}
        >
          Save note
        </button>
        <Result state={noteState} />
      </section>
    </div>
  );
}
