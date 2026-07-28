import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { formatOrderDate, getOrder, type OrderDetail } from "@/lib/orders";
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

/** Statuses where "no tracking yet" is a fact about time rather than about the order.
 * Anything else (cancelled/expired/refunded — never shipping; delivered/completed —
 * already there; shipped with the fields still blank) gets no tracking section at all:
 * "you'll get tracking when it ships" on a cancelled order is worse than silence. */
const PRE_SHIP = new Set(["pending_payment", "processing", "on_hold"]);

// The account layout already sets robots noindex for everything beneath it.
export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { number } = await params;
  return { title: `Order ${number}` };
}

async function loadOrder(number: string, country: string): Promise<OrderDetail> {
  try {
    return await getOrder(number, country, pagePath(number));
  } catch (e) {
    // 403 as well as 404: the backend deliberately refuses to distinguish "no such order"
    // from "not yours" (orders/views.py filters by owner so a stranger's order 404s — a
    // 403 would confirm it exists). Mirror that here rather than surfacing an error page.
    if (e instanceof ApiError && (e.status === 404 || e.status === 403)) notFound();
    // Anything else — including the NEXT_REDIRECT that getOrder throws to renew a stale
    // session — must propagate untouched.
    throw e;
  }
}

export default async function OrderDetailPage({ params }: { params: Params }) {
  const { number } = await params;
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const order = await loadOrder(number, country);

  const tracking = [order.tracking_carrier, order.tracking_number]
    .filter((v) => v && v.trim())
    .join(" · ");
  // Only the predicate is borrowed from the confirmation page: its banner copy is
  // just-placed-an-order language ("your order is reserved"), wrong on a page a customer
  // opens weeks later. The bank block itself is still what an unpaid transfer needs.
  const showBankDetails = confirmationCopy({
    gateway: order.payment_gateway,
    status: order.status,
  }).showBankDetails;

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

      {(tracking || PRE_SHIP.has(order.status)) && (
        <div className="mt-6">
          <h2 className="font-display text-lg">Tracking</h2>
          <p className="mt-2 text-sm text-muted">
            {tracking || "You'll get tracking details when your order ships."}
          </p>
        </div>
      )}

      {showBankDetails && (
        <div className="mt-8 border-t border-line pt-6">
          <ConfirmationBankDetails
            number={order.number}
            amount={order.grand_total}
            currency={order.currency}
          />
        </div>
      )}

      <div className="mt-8 flex flex-wrap items-center gap-4">
        {/* Plain <a>, never next/link: this is a file download served by a BFF route
            (Task 4), and a client-side navigation to it would try to render a PDF as a
            React page. `download` keeps the customer on this page. */}
        <a
          href={`/api/orders/${encodeURIComponent(number)}/invoice`}
          download
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
