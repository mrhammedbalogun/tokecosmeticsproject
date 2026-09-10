"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { MenuEntry } from "@/lib/shop-menu";

/**
 * The "Shop by Category" nav menu.
 *
 * ── WHY A PANEL AND NOT A LIST ──────────────────────────────────────────────────────────
 *
 * The menu is now two levels deep in three places — Shop By Skin Concerns, Shop By Edit,
 * Shop By Skin Tone. A 224px single-column list cannot show a second level without either
 * a nested flyout (a submenu that opens on hover, at the edge of the viewport, needing a
 * diagonal mouse path to reach — the classic thing that fights every user) or indentation
 * so deep the panel becomes a scrolling column. A single wide panel shows all sixteen
 * destinations at once, which is the point of a menu.
 *
 * ── CLICK, NOT HOVER ────────────────────────────────────────────────────────────────────
 *
 * Kept from the first version: hover menus have no touch equivalent and trap keyboard
 * users. It closes on outside click, on Escape (returning focus to the button, or the
 * shopper is left tabbing from the top of the document), and on navigation.
 */
export function CategoryDropdown({ entries }: { entries: MenuEntry[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (entries.length === 0) return null;

  const close = () => setOpen(false);
  // Plain links and groups are laid out differently, so they are collected separately
  // rather than sorted into a single grid: four one-line links do not want a column each.
  const links = entries.flatMap((e) => (e.kind === "link" ? [e.link] : []));
  const groups = entries.flatMap((e) => (e.kind === "group" ? [e.group] : []));

  return (
    <div ref={ref} className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-1 text-sm hover:text-accent"
      >
        Shop by Category
        <svg
          aria-hidden
          viewBox="0 0 12 12"
          className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`}
        >
          <path d="M2 4l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </button>

      {open && (
        <div
          // Anchored to the button but clamped to the viewport: at 1024px a 900px panel
          // hanging off a nav item two-thirds across the bar would run off the right edge.
          className="absolute left-0 top-full z-50 mt-2 w-[min(56rem,calc(100vw-2rem))] rounded-[var(--radius-card)] border border-line bg-surface p-6 shadow-xl"
        >
          <div className="grid gap-x-8 gap-y-6 sm:grid-cols-2 lg:grid-cols-4">
            {/* The plain categories, together in the first column — the shelves. */}
            {links.length > 0 && (
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
                  Shop
                </p>
                <ul className="mt-3 space-y-1">
                  {links.map((link) => (
                    <li key={link.href}>
                      <Link
                        href={link.href}
                        onClick={close}
                        className="-mx-2 block rounded px-2 py-1.5 text-sm hover:bg-background hover:text-accent"
                      >
                        {link.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {groups.map((group) => (
              <div key={group.label}>
                {/* The heading is a LINK when the group has a page of its own — a shopper
                    who clicks "Shop By Skin Concerns" gets every concern product, not a
                    swallowed click. "Shop By Edit" has no such page, so it is plain text. */}
                {group.href ? (
                  <Link
                    href={group.href}
                    onClick={close}
                    className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted hover:text-accent"
                  >
                    {group.label}
                  </Link>
                ) : (
                  <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
                    {group.label}
                  </p>
                )}
                <ul className="mt-3 space-y-1">
                  {group.links.map((link) => (
                    <li key={link.href}>
                      <Link
                        href={link.href}
                        onClick={close}
                        className="-mx-2 block rounded px-2 py-1.5 hover:bg-background"
                      >
                        <span className="block text-sm hover:text-accent">{link.label}</span>
                        {link.note && (
                          <span className="block text-xs text-muted">{link.note}</span>
                        )}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <div className="mt-6 border-t border-line pt-4">
            <Link
              href="/products"
              onClick={close}
              className="text-sm font-medium text-accent hover:underline"
            >
              Shop all products →
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
