"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

interface Category { name: string; slug: string }

/** The "Shop by Category" nav dropdown (artifact menu structure). Click-to-open
 * rather than hover: hover menus fail on touch and trap keyboard users. Closes
 * on outside click, Escape, and navigation. */
export function CategoryDropdown({ categories }: { categories: Category[] }) {
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
  if (categories.length === 0) return null;
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-1 text-sm hover:text-accent"
      >
        Shop by Category
        <svg aria-hidden viewBox="0 0 12 12" className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`}>
          <path d="M2 4l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </button>
      {open && (
        <ul className="absolute left-0 top-full z-50 mt-2 w-56 rounded-[var(--radius-card)] border border-line bg-surface py-2 shadow-lg">
          {categories.map((c) => (
            <li key={c.slug}>
              <Link
                href={`/category/${c.slug}`}
                onClick={() => setOpen(false)}
                className="block px-4 py-2 text-sm hover:bg-background hover:text-accent"
              >
                {c.name}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
