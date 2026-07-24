import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { ApiError } from "@/lib/api";
import { COUNTRY_COOKIE, DEFAULT_COUNTRY, formatMoney, symbolFor } from "@/lib/country";
import { getOrder, type OrderDetail } from "@/lib/checkout";
import { ConfirmationBankDetails } from "@/components/checkout/ConfirmationBankDetails";

type Params = Promise<{ number: string }>;

export const metadata: Metadata = { title: "Order confirmed", robots: { index: false } };

async function loadOrder(number: string, country: string): Promise<OrderDetail> {
  try {
    return await getOrder(number, country);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}

/** The address snapshot on an order is an untyped JSON blob (see OrderDetail.shipping_
 * address in lib/checkout.ts) — it's a point-in-time copy of an Address row, not a
 * live reference, so it's read defensively here rather than assumed to match the
 * Address shape exactly. */
function str(addr: Record<string, unknown> | null, key: string): string | undefined {
  const v = addr?.[key];
  return typeof v === "string" && v.trim() ? v : undefined;
}

function AddressSummary({ address }: { address: Record<string, unknown> | null }) {
  if (!address) return <p className="text-sm text-muted">No address on file.</p>;
  const name = [str(address, "first_name"), str(address, "last_name")].filter(Boolean).join(" ");
  const lines = [
    name,
    str(address, "line1"),
    str(address, "line2"),
    [str(address, "city_text"), str(address, "state_text")].filter(Boolean).join(", "),
    str(address, "postcode"),
    str(address, "phone"),
  ].filter((l): l is string => Boolean(l && l.trim()));

  if (lines.length === 0) return <p className="text-sm text-muted">No address on file.</p>;

  return (
    <address className="text-sm not-italic text-muted">
      {lines.map((line, i) => (
        <span key={i} className="block">
          {line}
        </span>
      ))}
    </address>
  );
}

export default async function ConfirmationPage({ params }: { params: Params }) {
  const { number } = await params;
  const country = (await cookies()).get(COUNTRY_COOKIE)?.value ?? DEFAULT_COUNTRY;
  const order = await loadOrder(number, country);
  const sym = symbolFor(order.currency);

  return (
    <section className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="font-display text-2xl">Thank you — your order is confirmed</h1>
      <p className="mt-2 text-sm text-muted">
        Order <span className="font-medium text-foreground">{order.number}</span> · Status:{" "}
        {order.status}
      </p>

      <div className="mt-6 rounded-[var(--radius-card)] border border-line bg-beige p-4 text-sm">
        Your order is reserved. Complete your bank transfer using the details below; we&apos;ll
        confirm and dispatch once payment arrives.
      </div>

      <div className="mt-8 space-y-3">
        <h2 className="font-display text-lg">Items</h2>
        {order.items.map((item, i) => (
          <div key={i} className="flex items-center justify-between gap-4 border-b border-line pb-3 text-sm">
            <div>
              <p className="font-medium">{item.product_name}</p>
              {Object.values(item.variant_name).length > 0 && (
                <p className="text-muted">{Object.values(item.variant_name).join(" / ")}</p>
              )}
              <p className="text-muted">Qty {item.quantity}</p>
            </div>
            <span className="font-medium">{item.line_total_display}</span>
          </div>
        ))}
      </div>

      <dl className="mt-6 space-y-2 border-t border-line pt-4 text-sm">
        <div className="flex justify-between gap-4">
          <dt className="text-muted">Subtotal</dt>
          <dd>{formatMoney(order.subtotal, order.currency, sym)}</dd>
        </div>
        {order.discount_total !== "0.00" && (
          <div className="flex justify-between gap-4">
            <dt className="text-muted">Discount</dt>
            <dd>−{formatMoney(order.discount_total, order.currency, sym)}</dd>
          </div>
        )}
        <div className="flex justify-between gap-4">
          <dt className="text-muted">Delivery</dt>
          <dd>{formatMoney(order.shipping_total, order.currency, sym)}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted">Tax</dt>
          <dd>{formatMoney(order.tax_total, order.currency, sym)}</dd>
        </div>
        <div className="flex justify-between gap-4 border-t border-line pt-2 text-base font-medium">
          <dt>Total</dt>
          <dd>{order.grand_total_display}</dd>
        </div>
      </dl>

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

      <div className="mt-8 border-t border-line pt-6">
        <ConfirmationBankDetails
          number={order.number}
          amount={order.grand_total}
          currency={order.currency}
        />
      </div>

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
