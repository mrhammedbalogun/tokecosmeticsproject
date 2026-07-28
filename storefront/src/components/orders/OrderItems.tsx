import type { OrderItem } from "@/lib/orders";

/** Order lines, shared by the confirmation page and the account order pages. Pure
 * presentation — the caller fetches the order. */
export function OrderItems({ items }: { items: OrderItem[] }) {
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
    </div>
  );
}
