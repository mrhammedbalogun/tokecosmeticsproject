"use client";
import { useCart } from "@/hooks/useCart";
import { formatMoney } from "@/lib/country";

export function CartDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { cart, setQty } = useCart();
  return (
    <div
      aria-hidden={!open}
      // overflow-hidden clips the off-canvas <aside> (translate-x-full) when closed —
      // without it the drawer sits 360px off-screen right and every page can scroll
      // horizontally on mobile. Harmless when open (drawer is translate-x-0, in-bounds).
      className={`fixed inset-0 z-50 overflow-hidden transition-opacity ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}
    >
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <aside
        role="dialog"
        aria-label="Shopping bag"
        className={`absolute right-0 top-0 h-full w-full max-w-md bg-surface shadow-xl transition-transform ${open ? "translate-x-0" : "translate-x-full"}`}
      >
        <header className="flex items-center justify-between border-b border-line p-5">
          <h2 className="font-display text-xl">Your bag</h2>
          <button onClick={onClose} aria-label="Close bag" className="text-muted hover:text-foreground">✕</button>
        </header>
        <div className="max-h-[calc(100%-9rem)] overflow-y-auto p-5">
          {cart.items.length === 0 ? (
            <p className="text-muted">Your bag is empty.</p>
          ) : (
            cart.items.map((l) => (
              <div key={l.id} className="flex items-center justify-between border-b border-line py-3">
                <div>
                  <p className="font-medium">{l.name}</p>
                  <p className="text-sm text-muted">Qty {l.quantity}</p>
                </div>
                <div className="flex items-center gap-3">
                  <span>{l.line_total ? formatMoney(l.line_total, cart.currency, "") : "—"}</span>
                  <button
                    aria-label={`Remove ${l.name}`}
                    onClick={() => setQty.mutate({ variantId: l.variant_id, quantity: 0 })}
                    className="text-muted hover:text-foreground"
                  >✕</button>
                </div>
              </div>
            ))
          )}
        </div>
        <footer className="absolute bottom-0 w-full border-t border-line p-5">
          <div className="mb-3 flex justify-between font-medium">
            <span>Subtotal</span>
            <span>{formatMoney(cart.subtotal, cart.currency, "")}</span>
          </div>
          <a href="/checkout" className="block rounded-[var(--radius-card)] bg-accent py-3 text-center text-surface hover:bg-accent-strong transition-colors">
            Checkout
          </a>
        </footer>
      </aside>
    </div>
  );
}
