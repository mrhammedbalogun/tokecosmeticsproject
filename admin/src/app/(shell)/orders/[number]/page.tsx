import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AajPanel, type AajPanelData } from "@/components/order/AajPanel";
import { GigPanel, type GigPanelData } from "@/components/order/GigPanel";
import { OrderOpsPanel } from "@/components/order/OrderOpsPanel";
import { PaymentPanel } from "@/components/order/PaymentPanel";
import { getAdminMeOrNull } from "@/lib/admin-me";
import { ApiError } from "@/lib/api";
import { addressLines, totalRows, type OrderDetail } from "@/lib/order-detail";
import { statusLabel } from "@/lib/orders";
import { fetchWithAuthOrBounce, requireAdmin } from "@/lib/session";
import {
  confirmReceiptAction,
  gatewayRefundAction,
  aajCaptureAction,
  aajCheckAction,
  aajLabelAction,
  aajVoidAction,
  gigCaptureAction,
  gigLabelAction,
  manualRefundAction,
  noteAction,
  resolveReviewAction,
  trackingAction,
  transitionAction,
} from "./actions";

export const metadata: Metadata = { title: "Order" };

type Params = Promise<{ number: string }>;

/**
 * `/orders/[number]` — one order, and everything that can be done to it.
 *
 * LOADING THIS PAGE WRITES AN AUDIT ROW. `AdminOrderDetailView` is read-audited: this is
 * the customer's name, email, phone, both addresses and the payment history on one screen.
 *
 * `fetchWithAuthOrBounce`, never `fetchWithAuth` — a Server Component cannot persist a
 * rotated refresh token. Every WRITE on this page is a Server Function, which can.
 *
 * THE OPERATOR'S SCOPES ARE FETCHED so the transition buttons can be greyed rather than
 * hidden. That is presentation only: `allowed_transitions` already carries the scope each
 * move needs, and the endpoint re-checks it on every request from the database.
 */
export default async function OrderDetailPage({ params }: { params: Params }) {
  const { number } = await params;
  const path = `/orders/${number}`;
  await requireAdmin(path);

  const [orderResult, meResult, gigResult, aajResult] = await Promise.allSettled([
    fetchWithAuthOrBounce<OrderDetail>(`/admin/orders/${encodeURIComponent(number)}/`, path),
    // Never throws and never redirects — answers null on anything going wrong.
    getAdminMeOrNull(),
    // {shipment: null} for a non-GIG order; a failure here costs the panel, not the page.
    fetchWithAuthOrBounce<GigPanelData>(`/admin/orders/${encodeURIComponent(number)}/gig/`, path),
    // Same shape for AAJ (Plan-43): {shipment: null} when the order is not an AAJ one.
    fetchWithAuthOrBounce<AajPanelData>(`/admin/orders/${encodeURIComponent(number)}/aaj/`, path),
  ]);

  for (const result of [orderResult, meResult]) {
    if (result.status === "rejected" && !(result.reason instanceof ApiError)) throw result.reason;
  }

  if (orderResult.status === "rejected") {
    const error = orderResult.reason as ApiError;
    if (error.status === 404) notFound();
    return (
      <p className="rounded-[var(--radius-card)] border border-warn/30 bg-warn/5 p-4 text-sm text-warn">
        {error.status === 403
          ? "Your role does not include access to orders."
          : "That order could not be loaded."}
      </p>
    );
  }

  const order = orderResult.value;
  // A failed scope lookup costs the greying-out, never the page — the endpoint is the
  // fence either way, so the buttons stay enabled and an unauthorised move 403s honestly.
  const scopes = meResult.status === "fulfilled" ? (meResult.value?.scopes ?? []) : [];
  const gig = gigResult.status === "fulfilled" && gigResult.value?.shipment ? gigResult.value : null;
  const aaj = aajResult.status === "fulfilled" && aajResult.value?.shipment ? aajResult.value : null;

  return (
    <div>
      <Link href="/orders" className="text-xs text-muted underline-offset-2 hover:underline">
        ← Orders
      </Link>

      <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-mono text-lg font-semibold tracking-tight">{order.number}</h1>
          <p className="mt-1 text-sm text-muted">
            {statusLabel(order.status)}
            {order.placed_at && ` · placed ${order.placed_at.slice(0, 10)}`}
            {order.source && order.source !== "web" && ` · ${order.source}`}
            {order.legacy_number && ` · was ${order.legacy_number}`}
          </p>
        </div>
        <a
          href={`/api/admin/orders/${order.number}/invoice.pdf`}
          className="shrink-0 rounded border border-line px-3 py-1.5 text-sm hover:border-accent"
        >
          Invoice
        </a>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-[1fr_24rem]">
        <div className="space-y-4">
          <section className="rounded-[var(--radius-card)] border border-line p-4">
            <h2 className="text-sm font-medium">Items</h2>
            <ul className="mt-3 space-y-2">
              {order.items.map((item, i) => (
                <li key={`${item.sku}-${i}`} className="flex justify-between gap-4 text-sm">
                  <span>
                    {item.product_name}
                    {item.variant_name && (
                      <span className="text-muted"> · {item.variant_name}</span>
                    )}
                    <span className="ml-2 font-mono text-xs text-muted">{item.sku}</span>
                    <span className="ml-2 text-muted">× {item.quantity}</span>
                  </span>
                  <span className="shrink-0 tabular-nums">{item.line_total_display}</span>
                </li>
              ))}
            </ul>

            <table className="mt-4 w-full border-t border-line pt-2 text-sm">
              <tbody>
                {totalRows(order).map((row) => (
                  <tr key={row.label} className={row.strong ? "font-medium" : ""}>
                    <td className="py-0.5">{row.label}</td>
                    <td className="py-0.5 text-right tabular-nums">{row.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <PaymentPanel
            number={order.number}
            payments={order.payments}
            currency={order.currency}
            grandTotal={order.grand_total}
            confirmReceipt={confirmReceiptAction}
          />

          <section className="rounded-[var(--radius-card)] border border-line p-4">
            <h2 className="text-sm font-medium">Timeline</h2>
            {order.events.length === 0 ? (
              <p className="mt-2 text-sm text-muted">Nothing recorded yet.</p>
            ) : (
              <ol className="mt-3 space-y-2 text-sm">
                {[...order.events].reverse().map((event, i) => (
                  <li key={i} className="flex gap-3">
                    <span className="w-36 shrink-0 text-xs text-muted">
                      {event.created_at.slice(0, 16).replace("T", " ")}
                    </span>
                    <span>
                      <span className="font-medium">{event.type}</span>
                      {event.message && ` — ${event.message}`}
                      {/* "system" for machine-driven events, so the timeline never reads
                          as though somebody forgot to sign their work. */}
                      <span className="ml-2 text-xs text-muted">{event.actor_name}</span>
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </div>

        <div className="space-y-4">
          <section className="rounded-[var(--radius-card)] border border-line p-4 text-sm">
            <h2 className="text-sm font-medium">Customer</h2>
            <p className="mt-2">{order.email || "—"}</p>
            {order.phone && <p className="text-muted">{order.phone}</p>}
            {order.user_email && order.user_email !== order.email && (
              <p className="text-xs text-muted">account: {order.user_email}</p>
            )}

            {order.pickup_store ? (
              <>
                <h3 className="mt-4 text-xs font-medium text-muted">Customer pickup at</h3>
                <p className="mt-1">
                  {order.pickup_store.name}
                  <br />
                  <span className="text-muted">{order.pickup_store.address}</span>
                  {order.pickup_store.phone && (
                    <>
                      <br />
                      <span className="text-muted">{order.pickup_store.phone}</span>
                    </>
                  )}
                </p>
              </>
            ) : (
              <>
                <h3 className="mt-4 text-xs font-medium text-muted">Delivering to</h3>
                <address className="mt-1 not-italic">
                  {addressLines(order.shipping_address).map((line, i) => (
                    <div key={i}>{line}</div>
                  ))}
                </address>
              </>
            )}
            {order.delivery_option_name && (
              <p className="mt-2 text-xs text-muted">{order.delivery_option_name}</p>
            )}
            {order.customer_note && (
              <>
                <h3 className="mt-4 text-xs font-medium text-muted">Their note</h3>
                <p className="mt-1">{order.customer_note}</p>
              </>
            )}
          </section>

          {gig && (
            <GigPanel
              number={order.number}
              data={gig}
              scopes={scopes}
              actions={{ capture: gigCaptureAction, label: gigLabelAction }}
            />
          )}
          {aaj && (
            <AajPanel
              number={order.number}
              data={aaj}
              scopes={scopes}
              actions={{
                capture: aajCaptureAction,
                check: aajCheckAction,
                void: aajVoidAction,
                label: aajLabelAction,
              }}
            />
          )}

          <OrderOpsPanel
            order={order}
            scopes={scopes}
            actions={{
              transition: transitionAction,
              tracking: trackingAction,
              note: noteAction,
              resolveReview: resolveReviewAction,
              gatewayRefund: gatewayRefundAction,
              manualRefund: manualRefundAction,
            }}
          />
        </div>
      </div>
    </div>
  );
}
