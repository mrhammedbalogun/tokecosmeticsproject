import type { Metadata } from "next";
import { cookies } from "next/headers";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { getOrderOrNotFound } from "@/lib/orders";
import { confirmationCopy } from "@/lib/confirmation-copy";
import { ConfirmationBankDetails } from "@/components/checkout/ConfirmationBankDetails";
import { AddressSummary } from "@/components/orders/AddressBlock";
import { OrderItems } from "@/components/orders/OrderItems";
import { StatusChip } from "@/components/orders/StatusChip";
import { OrderTotals } from "@/components/orders/OrderTotals";

type Params = Promise<{ number: string }>;

export const metadata: Metadata = { title: "Order confirmed", robots: { index: false } };

export default async function ConfirmationPage({ params }: { params: Params }) {
  const { number } = await params;
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  // `params` arrives DECODED, so the bounce target has to be re-encoded to match the URL
  // the browser is actually on — otherwise a legacy "#" or "/" in the number sends the
  // customer somewhere else after a session renewal.
  const order = await getOrderOrNotFound(
    number, country, `/checkout/confirmation/${encodeURIComponent(number)}`,
  );
  const copy = confirmationCopy({ gateway: order.payment_gateway, status: order.status });

  return (
    <section className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="font-display text-2xl">Thank you — your order is confirmed</h1>
      <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted">
        <span>
          Order <span className="font-medium text-foreground">{order.number}</span>
        </span>
        {/* Same chip as the account order list — a raw "pending_payment" here next to
            "Awaiting payment" there is a visible inconsistency to the same customer. */}
        <StatusChip status={order.status} />
      </p>

      <div className="mt-6 rounded-[var(--radius-card)] border border-line bg-beige p-4 text-sm">
        {copy.banner}
      </div>

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

      {copy.showBankDetails && (
        <div className="mt-8 border-t border-line pt-6">
          <ConfirmationBankDetails
            number={order.number}
            amount={order.grand_total}
            currency={order.currency}
          />
        </div>
      )}

      <p className="mt-8 text-sm text-muted">
        Your account is ready — you can track this order any time.
      </p>

      <a
        href="/products"
        className="mt-8 inline-block rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm font-medium text-surface transition-colors hover:bg-accent-strong"
      >
        Continue shopping
      </a>
    </section>
  );
}
