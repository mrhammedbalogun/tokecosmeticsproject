import type { Metadata } from "next";
import { cookies } from "next/headers";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError } from "@/lib/api";
import { ACCESS_COOKIE, GUEST_ORDER_COOKIE, REFRESH_COOKIE } from "@/lib/auth";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY } from "@/lib/country";
import { getGuestOrder, getOrderOrNotFound, type OrderDetail } from "@/lib/orders";
import { confirmationCopy } from "@/lib/confirmation-copy";
import { ConfirmationBankDetails } from "@/components/checkout/ConfirmationBankDetails";
import { PayAgain } from "@/components/checkout/PayAgain";
import { AddressSummary } from "@/components/orders/AddressBlock";
import { OrderItems } from "@/components/orders/OrderItems";
import { StatusChip } from "@/components/orders/StatusChip";
import { OrderTotals } from "@/components/orders/OrderTotals";

type Params = Promise<{ number: string }>;

export const metadata: Metadata = { title: "Order confirmed", robots: { index: false } };

export default async function ConfirmationPage({ params }: { params: Params }) {
  const { number } = await params;
  const jar = await cookies();
  const country = jar.get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  // Guest checkout (Plan-38): a guest arrives here seconds after PAYING, with no
  // session — bouncing them to /login was the exact post-payment dead end the plan's
  // dissent review flagged. The httpOnly guest-order cookie set at placement opens
  // the full order instead. The authed path is untouched; an authed customer with a
  // stale guest cookie still goes through their own session.
  const authed = Boolean(jar.get(ACCESS_COOKIE)?.value || jar.get(REFRESH_COOKIE)?.value);
  const guestToken = jar.get(GUEST_ORDER_COOKIE)?.value;
  const isGuestView = !authed && Boolean(guestToken);
  let order: OrderDetail;
  if (isGuestView) {
    try {
      order = await getGuestOrder(number, guestToken as string);
    } catch (e) {
      // Same mapping as getOrderOrNotFound: an expired/mismatched token must be
      // indistinguishable from a number that never existed.
      if (e instanceof ApiError && (e.status === 404 || e.status === 403)) notFound();
      throw e;
    }
  } else {
    // `params` arrives DECODED, so the bounce target has to be re-encoded to match
    // the URL the browser is actually on — otherwise a legacy "#" or "/" in the
    // number sends the customer somewhere else after a session renewal.
    order = await getOrderOrNotFound(
      number, country, `/checkout/confirmation/${encodeURIComponent(number)}`,
    );
  }
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

      {order.status === "pending_payment" && (
        // The pay-again surface (Plan-38 gap fix). This page is where the return page
        // now sends a FAILED redirect payment (authed or guest — the guest cookie
        // opens both the page and the pay endpoint), so it must offer a way to hand
        // over money. Copy differs by how they meant to pay: an online-gateway order
        // may also just be webhook-lagged, so that variant leads with "if it didn't
        // go through" rather than presuming failure; a transfer order gets a gentle
        // card alternative under its instructions.
        <div className="mt-8 border-t border-line pt-6">
          <PayAgain
            orderNumber={order.number}
            currentGateway={order.payment_gateway}
            country={order.country}
            {...(copy.showBankDetails
              ? {
                  title: "Prefer to pay another way?",
                  intro:
                    "You can also pay this order online — card payments confirm instantly, no transfer matching needed.",
                }
              : {
                  title: "Payment not completed?",
                  intro:
                    "If your payment didn't go through, you can try again or use a different method. Already paid? Sit tight — your confirmation email arrives as soon as it clears.",
                })}
          />
        </div>
      )}

      {isGuestView ? (
        <p className="mt-8 text-sm text-muted">
          We&apos;ve emailed your confirmation and a tracking link to{" "}
          <span className="font-medium text-foreground">{order.email || "your email"}</span>.
          Want order history and faster checkout next time?{" "}
          <Link href="/register" className="underline hover:text-foreground">
            Create an account
          </Link>{" "}
          with that email and this order will appear in it automatically.
        </p>
      ) : (
        <p className="mt-8 text-sm text-muted">
          Your account is ready — you can track this order any time.
        </p>
      )}

      <Link
        href="/products"
        className="mt-8 inline-block rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm font-medium text-surface transition-colors hover:bg-accent-strong"
      >
        Continue shopping
      </Link>
    </section>
  );
}
