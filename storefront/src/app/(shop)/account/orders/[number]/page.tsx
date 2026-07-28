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
import { TrackingBlock } from "@/components/orders/TrackingBlock";

type Params = Promise<{ number: string }>;
type Search = Promise<{ [key: string]: string | string[] | undefined }>;

/** Next hands `number` back DECODED, so the browser's actual URL has to be rebuilt to
 * be used as a path — both for the renewal bounce target and for the invoice href.
 * Migrated legacy numbers are not guaranteed URL-safe (see the list page's row href). */
const pagePath = (number: string) => `/account/orders/${encodeURIComponent(number)}`;

// The account layout already sets robots noindex for everything beneath it.
export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { number } = await params;
  return { title: `Order ${number}` };
}

export default async function OrderDetailPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: Search;
}) {
  const { number } = await params;
  // Set by the invoice BFF route when the upstream render fails: it 303s back here
  // rather than leaving a navigating browser on a blank error body, and this is the
  // only way it can say why. Purely cosmetic — an attacker setting it by hand gets
  // nothing but a sentence.
  const invoiceUnavailable = (await searchParams).invoice === "unavailable";
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const order = await getOrderOrNotFound(number, country, pagePath(number));

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

      {/* Shared with the guest tracking page — the PRE_SHIP ruling lives in the
          component now, not here. */}
      <TrackingBlock order={order} />

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

      {invoiceUnavailable && (
        <p role="status" className="mt-3 text-sm text-muted">
          We couldn&apos;t generate your invoice just now — try again in a few minutes.
        </p>
      )}
    </div>
  );
}
