"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { MORE_LINKS, MORE_MENU_LABEL } from "@/lib/site-pages";

/** The "More" nav dropdown.
 *
 * Replaced the flat `Blog` link in the header (2026-08-16): nine supporting pages were
 * due and the approved five-item nav had no room, so Blog moved inside and this trigger
 * took its slot. Links come from `lib/site-pages.ts` — see there for why they are code
 * routes rather than CMS pages.
 *
 * Behaviour is deliberately identical to `CategoryDropdown`: click-to-open rather than
 * hover (hover menus fail on touch and trap keyboard users), and it closes on outside
 * click, on Escape, and on navigation. Two menus in one nav that opened differently
 * would be worse than either choice on its own.
 */
export function MoreMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="true"
        className="flex items-center gap-1 text-sm hover:text-accent"
      >
        {MORE_MENU_LABEL}
        <svg aria-hidden viewBox="0 0 12 12" className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`}>
          <path d="M2 4l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </button>
      {open && (
        // RIGHT-ALIGNED, unlike the category menu's `left-0`. This is the last item in the
        // nav and the longest label in it ("Entrepreneurial Program") needs a wider panel
        // than the category one; opening leftwards keeps it off the search box.
        <ul className="absolute right-0 top-full z-50 mt-2 w-60 rounded-[var(--radius-card)] border border-line bg-surface py-2 shadow-lg">
          {MORE_LINKS.map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                onClick={() => setOpen(false)}
                className="block px-4 py-2 text-sm hover:bg-background hover:text-accent"
              >
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
