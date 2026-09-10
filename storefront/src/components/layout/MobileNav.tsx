"use client";
import Link from "next/link";
import { useState } from "react";
import { OverlayPortal } from "@/components/layout/OverlayPortal";
import { CountrySwitcher } from "@/components/layout/CountrySwitcher";
import type { Market } from "@/lib/country";
import { MORE_LINKS, MORE_MENU_LABEL } from "@/lib/site-pages";
import type { MenuEntry } from "@/lib/shop-menu";

/**
 * The drawer, and below `lg` the ONLY place the country/currency picker lives.
 *
 * It used to sit in the header at every width. A native `<select>` sizes itself to its
 * longest option, so it was 198px wide — measured 2026-08-16 — which on a 390px phone
 * squeezed the Toke logo to 0×0 and pushed the cart button off the right edge. A picker
 * that costs a shopper both the brand and their basket does not belong in a phone header;
 * in a drawer it is simply a row with room to spell itself out.
 *
 * `lg`, not `md`: at exactly 768 the desktop nav, the search box and the header actions
 * together overflowed by 36px, so tablets get the drawer too.
 */
export function MobileNav({
  menu,
  markets,
  country,
}: {
  menu: MenuEntry[];
  markets: Market[];
  country: string;
}) {
  const [open, setOpen] = useState(false);
  // Which groups are expanded. Sub-menus are COLLAPSED BY DEFAULT and open one at a time
  // is NOT enforced — a shopper comparing concerns against tones would have the first
  // group close under their thumb. Flat expansion of all sixteen destinations, meanwhile,
  // is a 1,400px drawer, which is the bug this file already carries a comment about.
  const [expanded, setExpanded] = useState<string[]>([]);
  const toggle = (label: string) =>
    setExpanded((current) =>
      current.includes(label) ? current.filter((l) => l !== label) : [...current, label],
    );
  return (
    <div className="lg:hidden">
      <button onClick={() => setOpen(true)} aria-label="Open menu" className="text-xl">☰</button>
      {open && (
        <OverlayPortal>
        <div className="fixed inset-0 z-50">
          <div className="absolute inset-0 bg-black/30" onClick={() => setOpen(false)} />
          {/* `overflow-y-auto` ADDED 2026-08-16 AND IT IS A BUG FIX, NOT POLISH. Measured
              on a 390x844 viewport: this list is 1400px tall (26 categories from the live
              API) inside an 844px box whose computed `overflow-y` was `visible`. The
              parent is `fixed inset-0`, so everything past ~844px was clipped and NOTHING
              could scroll it — the last eight categories were unreachable on a phone
              before this change, silently, and adding the `More` links would have buried
              all nine in the same dead zone. `overscroll-contain` stops a flick at the end
              of the list from scrolling the page behind the overlay. */}
          <nav
            className="absolute left-0 top-0 h-full w-72 overflow-y-auto overscroll-contain bg-surface p-6"
            aria-label="Mobile"
          >
            <button onClick={() => setOpen(false)} aria-label="Close menu" className="mb-6 text-muted">✕</button>
            <ul className="grid gap-3">
              <li><Link href="/" onClick={() => setOpen(false)} className="font-medium hover:text-accent">Home</Link></li>
              <li><Link href="/products" onClick={() => setOpen(false)} className="font-medium hover:text-accent">All Products</Link></li>
              <li><Link href="/combo" onClick={() => setOpen(false)} className="font-medium hover:text-accent">Combo Deals</Link></li>
              <li><Link href="/skin-quiz" onClick={() => setOpen(false)} className="font-medium hover:text-accent">Skin Quiz</Link></li>
              {/* The desktop header's `More` dropdown, flattened. A drawer has vertical
                  room a nav bar does not, so these are listed under a heading rather than
                  hidden behind a second tap — same links, same order, one source
                  (`lib/site-pages.ts`).

                  ABOVE the categories deliberately: that list is whatever the catalogue
                  currently holds (26 rows today and growing), so anything placed after it
                  keeps sinking further down the drawer. A fixed nine-item block goes
                  first; the unbounded one goes last. */}
              <li className="mt-4 text-xs uppercase tracking-[0.16em] text-muted">{MORE_MENU_LABEL}</li>
              {MORE_LINKS.map((item) => (
                <li key={item.href}>
                  <Link href={item.href} onClick={() => setOpen(false)} className="hover:text-accent">
                    {item.label}
                  </Link>
                </li>
              ))}
              <li className="mt-4 text-xs uppercase tracking-[0.16em] text-muted">Shop by Category</li>
              {menu.map((entry) =>
                entry.kind === "link" ? (
                  <li key={entry.link.href}>
                    <Link href={entry.link.href} onClick={() => setOpen(false)} className="hover:text-accent">
                      {entry.link.label}
                    </Link>
                  </li>
                ) : (
                  <li key={entry.group.label}>
                    {/* The row is a BUTTON, and the group's own page (where it has one) is
                        the first item inside it. Making the row itself a link with a
                        separate chevron target puts a navigation and a disclosure inside
                        one thumb-width, and on a phone the wrong one fires. */}
                    <button
                      type="button"
                      onClick={() => toggle(entry.group.label)}
                      aria-expanded={expanded.includes(entry.group.label)}
                      className="flex w-full items-center justify-between text-left hover:text-accent"
                    >
                      <span>{entry.group.label}</span>
                      <svg
                        aria-hidden
                        viewBox="0 0 12 12"
                        className={`h-3 w-3 shrink-0 transition-transform ${
                          expanded.includes(entry.group.label) ? "rotate-180" : ""
                        }`}
                      >
                        <path d="M2 4l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" />
                      </svg>
                    </button>
                    {expanded.includes(entry.group.label) && (
                      <ul className="mt-2 grid gap-2 border-l border-line pl-3">
                        {entry.group.href && (
                          <li>
                            <Link
                              href={entry.group.href}
                              onClick={() => setOpen(false)}
                              className="text-sm text-muted hover:text-accent"
                            >
                              All {entry.group.label.replace(/^Shop By /i, "")}
                            </Link>
                          </li>
                        )}
                        {entry.group.links.map((link) => (
                          <li key={link.href}>
                            <Link
                              href={link.href}
                              onClick={() => setOpen(false)}
                              className="text-sm hover:text-accent"
                            >
                              {link.label}
                            </Link>
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ),
              )}
            </ul>

            {markets.length > 0 && (
              <div className="mt-8 border-t border-line pt-6">
                <p className="text-xs uppercase tracking-[0.16em] text-muted">
                  Country and currency
                </p>
                {/* Closes the drawer on change: `router.refresh()` repaints the prices
                    behind it, and leaving the menu open would hide the very thing the
                    customer just changed. */}
                <CountrySwitcher
                  markets={markets}
                  current={country}
                  onChanged={() => setOpen(false)}
                  className="mt-3 flex w-full items-center text-sm"
                />
              </div>
            )}
          </nav>
        </div>
        </OverlayPortal>
      )}
    </div>
  );
}
