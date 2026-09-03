"use client";

/**
 * A bundle in the bag — one card, one quantity, one saving.
 *
 * ── THE COMPONENTS ARE SHOWN BUT NOT EDITABLE, AND THAT IS THE POINT ────────────────
 *
 * A combo is bought whole: it is priced as a set, so a set is what leaves the shop. Per
 * component steppers would let somebody drop the cleanser from a "3 for the price of
 * 2.7" box and expect the bundle price to hold. So the contents read as a manifest, and
 * the one control on the card resizes the whole box — which is also the only thing the
 * server will accept (`carts.services.set_combo_quantity`).
 *
 * ── THE SAVING IS STATED ONCE ───────────────────────────────────────────────────────
 *
 * The rows carry FULL prices and the discount is a single line, because that is exactly
 * how it reaches the order (`Order.combo_discount_total`) and the confirmation email. A
 * cart that smeared the saving across four rows would not reconcile against the receipt
 * the customer gets ten minutes later.
 *
 * Shared by the drawer and the cart page so the two views of one bag cannot drift; the
 * `compact` variant is the 384px drawer.
 */
import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import type { CartCombo } from "@/lib/cart-types";
import { formatMoney } from "@/lib/country";
import { mediaUrl } from "@/lib/media";

export function CartComboCard({
  combo,
  currency,
  onQuantity,
  onNavigate,
  compact = false,
}: {
  combo: CartCombo;
  currency: string;
  onQuantity: (quantity: number) => void;
  /** Called when a link inside is followed — the drawer uses it to close itself. */
  onNavigate?: () => void;
  compact?: boolean;
}) {
  // Open by default on the full cart page (there is room, and "what is in it" is the
  // question), collapsed in the drawer (there is not).
  const [open, setOpen] = useState(!compact);
  const img = mediaUrl(combo.image);
  const unitCount = combo.items.reduce((n, l) => n + l.quantity, 0);

  return (
    <div
      className={`rounded-[var(--radius-card)] border bg-surface ${
        combo.unavailable ? "border-line opacity-60" : combo.ended ? "border-line" : "border-accent/30"
      } ${compact ? "my-4" : ""}`}
    >
      <div className="flex gap-4 p-4">
        <Link
          href={`/combo/${combo.combo_slug}`}
          onClick={onNavigate}
          tabIndex={-1}
          aria-hidden
          className="relative h-20 w-20 shrink-0 overflow-hidden rounded-[10px] border border-line bg-beige"
        >
          {img && <Image src={img} alt="" fill sizes="80px" className="object-cover" />}
        </Link>

        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p
                className={`text-[10px] font-semibold uppercase tracking-[0.12em] ${
                  combo.ended ? "text-muted" : "text-accent"
                }`}
              >
                Combo
              </p>
              <p className="mt-0.5 min-w-0 font-medium leading-snug">
                <Link
                  href={`/combo/${combo.combo_slug}`}
                  onClick={onNavigate}
                  className="hover:text-accent"
                >
                  {combo.name}
                </Link>
              </p>
            </div>
            <div className="shrink-0 text-right">
              <span className="block text-sm font-medium tabular-nums">
                {combo.line_total ? formatMoney(combo.line_total, currency) : "—"}
              </span>
              {combo.components_total && combo.line_total !== combo.components_total && (
                <s className="block text-xs text-muted tabular-nums">
                  {formatMoney(combo.components_total, currency)}
                </s>
              )}
            </div>
          </div>

          {combo.unavailable ? (
            <div className="mt-2 flex items-center gap-3">
              <p className="text-sm text-accent">No longer available</p>
              <RemoveLink name={combo.name} onRemove={() => onQuantity(0)} />
            </div>
          ) : (
            <>
              {/* The DEAL ended; the products did not, and the till still charges for
                  them. Saying "no longer available" here would be a lie about goods
                  sitting in the bag — and the shopper would remove them believing they
                  had to. */}
              {combo.ended && (
                <p className="mt-1 text-xs text-muted">
                  This combo has ended — the products are still in your bag at their
                  usual prices.
                </p>
              )}
              {combo.saving && Number(combo.saving) > 0 && (
                <p className="mt-1 text-xs font-medium text-accent">
                  Saving {formatMoney(combo.saving, currency)}
                </p>
              )}
              <div className="mt-2 flex items-center justify-between gap-3">
                <ComboStepper
                  name={combo.name}
                  quantity={combo.quantity}
                  onChange={onQuantity}
                />
                <RemoveLink name={combo.name} onRemove={() => onQuantity(0)} />
              </div>
            </>
          )}
        </div>
      </div>

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between border-t border-line px-4 py-2 text-left text-xs text-muted transition-colors hover:text-foreground"
      >
        <span>
          {unitCount} {unitCount === 1 ? "product" : "products"} inside
        </span>
        <svg
          aria-hidden
          viewBox="0 0 24 24"
          className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open && (
        <ul className="border-t border-line px-4 py-2">
          {combo.items.map((line) => {
            const lineImg = mediaUrl(line.image);
            const options = Object.values(line.variant_name ?? {}).filter(Boolean).join(" · ");
            return (
              <li key={line.id} className="flex items-center gap-3 py-2">
                <span
                  aria-hidden
                  className="relative h-10 w-10 shrink-0 overflow-hidden rounded border border-line bg-beige"
                >
                  {lineImg && (
                    <Image src={lineImg} alt="" fill sizes="40px" className="object-cover" />
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm">
                    {line.product_slug ? (
                      <Link
                        href={`/product/${line.product_slug}`}
                        onClick={onNavigate}
                        className="hover:text-accent"
                      >
                        {line.name}
                      </Link>
                    ) : (
                      line.name
                    )}
                  </span>
                  {options && <span className="block text-xs text-muted">{options}</span>}
                </span>
                <span className="shrink-0 text-xs text-muted tabular-nums">
                  ×{line.quantity}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function ComboStepper({
  name,
  quantity,
  onChange,
}: {
  name: string;
  quantity: number;
  onChange: (quantity: number) => void;
}) {
  return (
    <div
      role="group"
      aria-label={`Number of ${name} combos`}
      className="inline-flex items-center rounded-[10px] border border-line"
    >
      <button
        type="button"
        aria-label={`One fewer ${name}`}
        onClick={() => onChange(Math.max(0, quantity - 1))}
        className="flex h-8 w-8 items-center justify-center rounded-l-[9px] text-muted transition-colors hover:bg-beige hover:text-foreground"
      >
        −
      </button>
      <span
        aria-live="polite"
        className="min-w-9 border-x border-line px-1 py-1 text-center text-sm tabular-nums"
      >
        {quantity}
      </span>
      <button
        type="button"
        aria-label={`One more ${name}`}
        onClick={() => onChange(quantity + 1)}
        className="flex h-8 w-8 items-center justify-center rounded-r-[9px] text-muted transition-colors hover:bg-beige hover:text-foreground"
      >
        +
      </button>
    </div>
  );
}

function RemoveLink({ name, onRemove }: { name: string; onRemove: () => void }) {
  return (
    <button
      type="button"
      aria-label={`Remove the ${name} combo`}
      onClick={onRemove}
      className="text-xs text-muted underline underline-offset-2 transition-colors hover:text-foreground"
    >
      Remove
    </button>
  );
}
