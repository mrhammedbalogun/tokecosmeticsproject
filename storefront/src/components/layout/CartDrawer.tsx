"use client";
import { useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useCart } from "@/hooks/useCart";
import { formatMoney } from "@/lib/country";
import { mediaUrl } from "@/lib/media";
import { stashCoupon } from "@/lib/coupon-storage";
import { OverlayPortal } from "@/components/layout/OverlayPortal";
import { ReferralCodeField } from "@/components/checkout/ReferralCodeField";
import type { CartLine } from "@/lib/cart-types";

/** Same pen as CartButton's BagIcon (1.5 stroke, round caps). Not imported from
 * there because CartButton imports this file — that would be a cycle. */
function BagIcon({ className = "h-[18px] w-[18px]" }: { className?: string }) {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className={className} fill="none"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5.5 8.5h13l-.9 10.6a2 2 0 0 1-2 1.9H8.4a2 2 0 0 1-2-1.9L5.5 8.5Z" />
      <path d="M9 8.5V7a3 3 0 0 1 6 0v1.5" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-5 w-5" fill="none"
      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg aria-hidden viewBox="0 0 24 24"
      className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}
      fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

/** "200ml · Shea" — the chosen options, when the product has any. */
function variantLabel(line: CartLine): string {
  return Object.values(line.variant_name ?? {}).filter(Boolean).join(" · ");
}

/** Joined −/qty/+ control. One bordered box rather than three loose circles so the
 * three parts read as one control at a glance (and so the number can't be mistaken
 * for the line's price, which sits on the same row). */
function QtyStepper({
  line, onChange,
}: { line: CartLine; onChange: (qty: number) => void }) {
  return (
    <div
      role="group"
      aria-label={`Quantity for ${line.name}`}
      className="inline-flex items-center rounded-[10px] border border-line"
    >
      <button
        type="button"
        aria-label={`Decrease quantity of ${line.name}`}
        onClick={() => onChange(Math.max(0, line.quantity - 1))}
        className="flex h-8 w-8 items-center justify-center rounded-l-[9px] text-muted transition-colors hover:bg-beige hover:text-foreground"
      >
        −
      </button>
      <span aria-live="polite" className="min-w-9 border-x border-line px-1 py-1 text-center text-sm tabular-nums">
        {line.quantity}
      </span>
      <button
        type="button"
        aria-label={`Increase quantity of ${line.name}`}
        onClick={() => onChange(line.quantity + 1)}
        className="flex h-8 w-8 items-center justify-center rounded-r-[9px] text-muted transition-colors hover:bg-beige hover:text-foreground"
      >
        +
      </button>
    </div>
  );
}

/** A discount box that deliberately does NOT validate.
 *
 * The quote endpoint that checks a code is authed-only, and the drawer shows no
 * totals breakdown for a discount to land in — so validating here would mean either
 * lying to guests or building a second OrderSummary into a 384px panel. Instead the
 * code is stashed (see lib/coupon-storage.ts) and ReviewStep pre-fills and applies
 * it. Collapsed by default: an open, empty "discount code" box makes every shopper
 * without one feel they are missing out. */
function DiscountBox({ onDone }: { onDone?: () => void }) {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [saved, setSaved] = useState(false);

  function save() {
    const value = code.trim();
    if (!value) return;
    stashCoupon(value);
    setSaved(true);
    onDone?.();
  }

  return (
    <div className="border-t border-line px-5 py-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between text-left text-sm font-medium hover:text-accent"
      >
        Got a discount code?
        <Chevron open={open} />
      </button>
      {open && (
        <div className="mt-3">
          <div className="flex gap-2">
            <label htmlFor="drawer-coupon" className="sr-only">Discount code</label>
            <input
              id="drawer-coupon"
              type="text"
              value={code}
              onChange={(e) => { setCode(e.target.value); setSaved(false); }}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); save(); } }}
              placeholder="Enter code"
              autoCapitalize="characters"
              autoComplete="off"
              spellCheck={false}
              className="min-w-0 flex-1 rounded-[var(--radius-card)] border border-line bg-beige px-3 py-2 text-sm uppercase placeholder:normal-case"
            />
            <button
              type="button"
              onClick={save}
              disabled={!code.trim()}
              className="rounded-[var(--radius-card)] bg-accent px-4 py-2 text-sm text-surface transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
            >
              Save
            </button>
          </div>
          <p aria-live="polite" className="mt-2 text-xs text-muted">
            {saved
              ? "Saved — we'll apply it at checkout."
              : "We'll check it and take it off your total at checkout."}
          </p>
        </div>
      )}
    </div>
  );
}

export function CartDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { cart, setQty } = useCart();
  const count = cart.items.reduce((n, l) => n + l.quantity, 0);

  // Escape closes it. A drawer that only closes by clicking a 20px ✕ or the scrim is
  // a trap for keyboard users, and the scrim isn't focusable.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <OverlayPortal>
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
        aria-label="Shopping cart"
        // flex column, NOT the old absolutely-positioned footer with a max-h calc():
        // the footer's height now varies (discount row opens, subtotal note wraps) and
        // a hard-coded 9rem reservation would either clip the list or leave a gap.
        className={`absolute right-0 top-0 flex h-full w-full max-w-md flex-col bg-surface shadow-xl transition-transform ${open ? "translate-x-0" : "translate-x-full"}`}
      >
        <header className="flex shrink-0 items-center justify-between border-b border-line px-5 py-4">
          <h2 className="font-display text-xl">
            {/* The space is its own text node, NOT inside the span: the accessible-name
                algorithm trims each element's contribution, so " (2)" inside the span
                announces as "Review Your Cart(2)". */}
            Review Your Cart
            {count > 0 && <>{" "}<span className="text-muted">({count})</span></>}
          </h2>
          <button onClick={onClose} aria-label="Close cart" className="text-muted transition-colors hover:text-foreground">
            <CloseIcon />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5">
          {cart.items.length === 0 ? (
            <div className="py-16 text-center">
              <BagIcon className="mx-auto h-10 w-10 text-line" />
              <p className="mt-3 text-muted">Your cart is empty.</p>
              <Link
                href="/products"
                onClick={onClose}
                className="mt-5 inline-block rounded-full bg-accent px-6 py-2.5 text-sm text-surface transition-colors hover:bg-accent-strong"
              >
                Start shopping
              </Link>
            </div>
          ) : (
            <ul>
              {cart.items.map((l) => {
                const img = mediaUrl(l.image);
                const options = variantLabel(l);
                const href = l.product_slug ? `/product/${l.product_slug}` : null;
                return (
                  <li
                    key={l.id}
                    className={`flex gap-4 border-b border-line py-4 last:border-b-0 ${l.unavailable ? "opacity-60" : ""}`}
                  >
                    {/* Fixed 80px square. bg-beige shows through for the products that
                        have no photograph yet, so the row keeps its shape either way. */}
                    <ImageCell href={href} img={img} onNavigate={onClose} />

                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-3">
                        <p className="min-w-0 font-medium leading-snug">
                          {href ? (
                            <Link href={href} onClick={onClose} className="hover:text-accent">{l.name}</Link>
                          ) : (
                            l.name
                          )}
                        </p>
                        <span className="shrink-0 text-sm font-medium tabular-nums">
                          {l.line_total ? formatMoney(l.line_total, cart.currency) : "—"}
                        </span>
                      </div>
                      {options && <p className="mt-0.5 text-xs text-muted">{options}</p>}

                      {l.unavailable ? (
                        <div className="mt-2 flex items-center gap-3">
                          <p className="text-sm text-accent">No longer available</p>
                          <RemoveButton line={l} onRemove={() => setQty.mutate({ variantId: l.variant_id, quantity: 0 })} />
                        </div>
                      ) : (
                        <div className="mt-2 flex items-center justify-between gap-3">
                          <QtyStepper
                            line={l}
                            onChange={(quantity) => setQty.mutate({ variantId: l.variant_id, quantity })}
                          />
                          <RemoveButton line={l} onRemove={() => setQty.mutate({ variantId: l.variant_id, quantity: 0 })} />
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {cart.items.length > 0 && (
          <div className="shrink-0">
            <DiscountBox />
            {/* Under the discount box, because to a shopper both are "a code I was
                given". This drawer's Checkout button goes straight to /checkout, so
                without this the two fastest routes to payment — "Buy now" and this
                button — both skipped every referral field the site had until the review
                step. No `onApplied`: the drawer shows a raw cart subtotal and no quote,
                so there is nothing here to redraw; the 5% appears on the next screen
                that prices anything. */}
            <ReferralCodeField variant="drawer" />
            <div className="border-t border-line px-5 pb-5 pt-4">
              <div className="flex items-baseline justify-between font-medium">
                <span>Subtotal</span>
                <span className="tabular-nums">{formatMoney(cart.subtotal, cart.currency)}</span>
              </div>
              <p className="mt-1 text-xs text-muted">Delivery &amp; taxes calculated at checkout.</p>

              {/* onClose because client-side navigation keeps this drawer mounted — the full
                  page load of a plain <a> used to close it as a side effect. */}
              <Link
                href="/checkout"
                onClick={onClose}
                className="mt-4 flex items-center justify-center gap-2 rounded-full bg-accent py-3.5 text-center font-medium text-surface transition-colors hover:bg-accent-strong"
              >
                <BagIcon />
                Checkout
                <span className="tabular-nums">{formatMoney(cart.subtotal, cart.currency)}</span>
              </Link>
              <button
                type="button"
                onClick={onClose}
                className="mt-3 block w-full text-center text-sm text-muted underline underline-offset-4 transition-colors hover:text-foreground"
              >
                Continue Shopping
              </button>
            </div>
          </div>
        )}
      </aside>
    </div>
    </OverlayPortal>
  );
}

/** alt="" and aria-hidden: the product name sits immediately to the right as its own
 * link, so announcing the picture too would read the row twice and put a second,
 * identical link in the tab order. tabIndex=-1 keeps the aria-hidden wrapper out of
 * it — an aria-hidden element that can still be focused is the worse bug. */
function ImageCell({
  href, img, onNavigate,
}: { href: string | null; img: string | null; onNavigate: () => void }) {
  const box = (
    <div className="relative h-20 w-20 shrink-0 overflow-hidden rounded-[10px] border border-line bg-beige">
      {/* object-cover, matching the server-side thumbnail's deliberate centre crop
          (apps/catalog/thumbnails.py) — and cropping the same way on the full-size
          fallback an unthumbnailed image falls back to. */}
      {img && <Image src={img} alt="" fill sizes="80px" className="object-cover" />}
    </div>
  );
  return href ? <Link href={href} onClick={onNavigate} tabIndex={-1} aria-hidden>{box}</Link> : box;
}

function RemoveButton({ line, onRemove }: { line: CartLine; onRemove: () => void }) {
  return (
    <button
      type="button"
      aria-label={`Remove ${line.name}`}
      onClick={onRemove}
      className="text-xs text-muted underline underline-offset-2 transition-colors hover:text-foreground"
    >
      Remove
    </button>
  );
}
