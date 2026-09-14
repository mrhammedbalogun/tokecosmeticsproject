import type { OrderItem } from "@/lib/orders";

/** Order lines, shared by the confirmation page and the account order pages. Pure
 * presentation — the caller fetches the order. */
export function OrderItems({ items }: { items: OrderItem[] }) {
  // The free gifts this order was promised. A gift has no price, no SKU and no line of
  // its own, so without this the customer's own record of the order says nothing about
  // it — and "where is my free gift" becomes a support ticket with no evidence on either
  // side. De-duplicated: the snapshot repeats on every line of the same bundle.
  const gifts = [...new Set(items.map((i) => i.combo_gift).filter(Boolean))] as string[];
  return (
    <div className="mt-8 space-y-3">
      <h2 className="font-display text-lg">Items</h2>
      {items.map((item, i) => (
        <div key={i} className="flex items-center justify-between gap-4 border-b border-line pb-3 text-sm">
          <div>
            <p className="font-medium">{item.product_name}</p>
            {item.variant_name && <p className="text-muted">{item.variant_name}</p>}
            <p className="text-muted">Qty {item.quantity}</p>
          </div>
          <span className="font-medium">{item.line_total_display}</span>
        </div>
      ))}
      {gifts.map((gift) => (
        <p key={gift} className="flex items-center gap-2 pb-3 text-sm">
          <span className="rounded-full bg-gold px-2.5 py-1 text-xs font-semibold">
            Free gift
          </span>
          <span>{gift}</span>
        </p>
      ))}
    </div>
  );
}
