import type { Metadata } from "next";
import Link from "next/link";
import { cookies } from "next/headers";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { formatOrderDate, getOrderOrNotFound } from "@/lib/orders";
import { confirmationCopy } from "@/lib/confirmation-copy";
import { ConfirmationBankDetails } from "@/components/checkout/ConfirmationBankDetails";
import { AddressSummary } from "@/components/orders/AddressBlock";
import { OrderItems } from "@/components/orders/OrderItems";
import { StatusChip } from "@/components/orders/StatusChip";
import { OrderTotals } from "@/components/orders/OrderTotals";

type Params = Promise<{ number: string }>;

/** Next hands `number` back DECODED, so the browser's actual URL has to be rebuilt to
 * be used as a path — both for the renewal bounce target and for the invoice href.
 * Migrated legacy numbers are not guaranteed URL-safe (see the list page's row href). */
const pagePath = (number: string) => `/account/orders/${encodeURIComponent(number)}`;

/** Statuses where "no tracking yet" is a fact about TIME — the order is on its way to
 * being shipped and simply has not got there. Everything else gets no tracking section
 * at all, because the hint would be a promise we have not made:
 *
 *  - cancelled/refunded are terminal; expired and on_hold can revive
 *    (`expired -> processing` is the late-payment path), but nothing is reserved or paid
 *    while they sit there, so no shipment is owed and none should be implied.
 *  - on_hold is a fact about the ORDER, not about time: it is the triage state for
 *    migrated legacy orders AND for the Plan-14a freight-declined cohort
 *    (backend/apps/orders/services.py:59), i.e. customers we OWE A REFUND. Telling one of
 *    them tracking is coming is a false promise about the wrong direction of money.
 *  - delivered/completed are already there; shipped-without-tracking has nothing to add.
 *
 * `backend/apps/orders/state.py` ALLOWED_TRANSITIONS is the authoritative status
 * vocabulary — diff this set against its keys when the backend adds a state (same
 * discipline as StatusChip). */
const PRE_SHIP = new Set(["pending_payment", "processing"]);

// The account layout already sets robots noindex for everything beneath it.
export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { number } = await params;
  return { title: `Order ${number}` };
}

export default async function OrderDetailPage({ params }: { params: Params }) {
  const { number } = await params;
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const order = await getOrderOrNotFound(number, country, pagePath(number));

  const trackingLine = [order.tracking_carrier, order.tracking_number]
    .filter((v) => v && v.trim())
    .join(" · ");
  // Only the predicate is borrowed from the confirmation page: its banner copy is
  // just-placed-an-order language ("your order is reserved"), wrong on a page a customer
  // opens weeks later. The bank block itself is still what an unpaid transfer needs.
  //
  // The extra status gate exists HERE and not on confirmation: confirmationCopy's
  // bank_transfer branch ignores status (fine there — the order was placed seconds ago
  // and can only be pending_payment), but order history serves the same order for years,
  // and "pay us by transfer" on a delivered, cancelled or refunded order is wrong enough
  // to prompt a duplicate payment.
  const showBankDetails =
    order.status === "pending_payment" &&
    confirmationCopy({ gateway: order.payment_gateway, status: order.status }).showBankDetails;

  return (
    <div>
      <h2 className="font-display text-2xl">Order {order.number}</h2>
      <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted">
        <span>Placed {formatOrderDate(order.placed_at)}</span>
        <StatusChip status={order.status} />
      </p>

      <OrderItems items={order.items} />

      <OrderTotals order={order} />

      <div className="mt-8 grid gap-6 sm:grid-cols-2">
        <div>
          <h2 className="font-display text-lg">Delivery address</h2>
          <div className="mt-2">
            <AddressSummary address={order.shipping_address} />
          </div>
        </div>
        <div>
          <h2 className="font-display text-lg">Delivery method</h2>
          <p className="mt-2 text-sm text-muted">{order.delivery_option_name ?? "—"}</p>
        </div>
      </div>

      {order.customer_note && (
        <div className="mt-6">
          <h2 className="font-display text-lg">Order note</h2>
          <p className="mt-2 text-sm text-muted">{order.customer_note}</p>
        </div>
      )}

      {(trackingLine || PRE_SHIP.has(order.status)) && (
        <div className="mt-6">
          <h2 className="font-display text-lg">Tracking</h2>
          <p className="mt-2 text-sm text-muted">
            {trackingLine || "You'll get tracking details when your order ships."}
          </p>
        </div>
      )}

      {showBankDetails && (
        // KNOWN LIMITATION (15c, accepted — on the checkpoint list). This component reads
        // the sessionStorage handoff stashed at checkout, so reached from order history —
        // a later visit, another tab, another device — it will usually fall back to its
        // "shown at checkout, contact support" note rather than the account details. That
        // fallback is still correct here: it names the amount and the order number and
        // makes clear payment is outstanding. A re-fetchable bank-instructions endpoint is
        // backend scope and is NOT being built in this plan.
        <div className="mt-8 border-t border-line pt-6">
          <ConfirmationBankDetails
            number={order.number}
            amount={order.grand_total}
            currency={order.currency}
          />
        </div>
      )}

      <div className="mt-8 flex flex-wrap items-center gap-4">
        {/* Plain <a>, never next/link: this is a file download served by a BFF route,
            and a client-side navigation to it would try to render a PDF as a React page.

            NO `download` ATTRIBUTE, deliberately. The route answers with two different
            kinds of response and the attribute would only serve one of them:
             - 200 carries `Content-Disposition: attachment`, which already downloads the
               PDF and leaves the customer sitting on this page. The attribute adds
               nothing.
             - a dead session gets a 303 to /login, and `download` survives a redirect —
               the browser would SAVE the login page as a file named after the order
               instead of showing it. Re-adding the attribute reintroduces exactly that. */}
        <a
          href={`/api/orders/${encodeURIComponent(order.number)}/invoice`}
          className="rounded-[var(--radius-card)] border border-line px-4 py-2 text-sm font-medium transition-colors hover:border-accent/60"
        >
          Download invoice (PDF)
        </a>
        <Link
          href="/account/orders"
          className="text-sm text-accent-strong underline underline-offset-2"
        >
          Back to orders
        </Link>
      </div>
    </div>
  );
}
